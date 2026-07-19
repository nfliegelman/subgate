# subgate

_One line: builds auto-updating browser filter lists that block NSFW subreddits, using Reddit's own 18+ flags as the authority, for Noah's own devices._

## What it does
Reddit marks every adult community with an internal 18+ flag. subgate reads those flags through Postpone's public mirror, collects extra candidate names from a second directory and from anything you paste into `manual_seeds.txt`, and publishes the confirmed 18+ communities as block lists plus a browser userscript. Your ad blocker subscribes to the lists; the userscript catches brand new communities and in-app navigation. No Reddit API key is needed. `force_block.txt` is your manual override for unflagged borderline communities.

## The pieces at a glance

| Piece | Lives in | Catches |
|---|---|---|
| Reddit account 18+ setting | Your Reddit account | Everything flagged, on every device, server side. The backbone. |
| subgate list in uBlock (Firefox) | Firefox | Direct visits and background traffic to 29k+ known subs |
| subgate list in AdGuard (Chrome) | Chrome | Same, on Chrome |
| subgate userscript (both browsers) | Violentmonkey / Tampermonkey | In-app clicks, ctrl+clicks, and subreddits created after the list was built |
| Feed hygiene rules (inside the lists) | Both browsers | NSFW thumbnails and blurred teasers in feeds and search |
| NextDNS | Every device on your DNS profile | old.reddit interstitial, gif and porn hosts, phone apps |

Repo creation and the first workflow run are covered click-by-click in **SETUP.md**. Everything below assumes the repo exists and the first run has finished. Replace `OWNER` with your GitHub username in every URL.

---

## Part 1: Reddit account setting (2 minutes, do this first)
1. On reddit.com, click your avatar in the top right, then **Settings**.
2. Open the **Preferences** section.
3. Turn **off** "Show mature content (I'm over 18)".
4. In the phone app: tap your profile picture, **Settings**, then look for the mature or 18+ toggle under Content or Feed and turn it off. Reddit renames this section periodically; search the settings for "mature" if you do not see it.

This is the only layer enforced by Reddit's own servers, so it works in every browser and the official app, including on your phone.

## Part 2: Firefox
**The list, in uBlock Origin:**
1. Install uBlock Origin from addons.mozilla.org if it is not installed.
2. Click the uBlock icon in the toolbar, then the gears symbol to open the Dashboard.
3. Open the **Filter lists** tab.
4. Scroll to the very bottom and tick the **Import...** checkbox. A text box appears.
5. Paste: `https://raw.githubusercontent.com/OWNER/subgate/main/subgate_full.txt`
6. Click **Apply changes** at the top left.
7. If you ever pasted rules into the **My filters** tab by hand: open that tab, select everything, delete it, Apply changes. The pasted copy never updates and will fight the subscription.

**The userscript, in Violentmonkey:**
1. Install Violentmonkey from addons.mozilla.org.
2. Open `https://raw.githubusercontent.com/OWNER/subgate/main/subgate.user.js` in a tab.
3. Violentmonkey opens an install page. Click **Confirm installation**.
4. If it asks about cross-origin permissions for raw.githubusercontent.com and api.postpone.app, allow them. That is how it downloads your list and checks new subreddits.

**Private windows (do not skip):**
1. Menu button, **Add-ons and themes**, **Extensions**.
2. Click **uBlock Origin**, set **Run in Private Windows** to **Allow**.
3. Click **Violentmonkey**, same setting, **Allow**.
Without this, private windows silently run with zero protection.

## Part 3: Chrome
**The list, in AdGuard:**
1. Install "AdGuard AdBlocker" from the Chrome Web Store.
2. Click the AdGuard icon, then the gear to open Settings.
3. Open **Filters**, then **Custom filters**.
4. Click **Add custom filter**, paste: `https://raw.githubusercontent.com/OWNER/subgate/main/subgate_chrome.txt`, confirm.
5. If AdGuard warns about a rule limit, lower `chrome_max_rules` in `sources.yaml`, commit, and re-run the workflow.

**The userscript, in Tampermonkey:**
1. Install Tampermonkey from the Chrome Web Store.
2. Go to `chrome://extensions`, turn on **Developer mode** with the toggle in the top right. Tampermonkey cannot run userscripts without it.
3. Open `https://raw.githubusercontent.com/OWNER/subgate/main/subgate.user.js`, Tampermonkey opens an install tab, click **Install**.

**Incognito (do not skip):**
1. Go to `chrome://extensions`.
2. Click **Details** on AdGuard, turn on **Allow in Incognito**.
3. Same for Tampermonkey.

**One test to run on Chrome:** type a known blocked subreddit URL directly and press Enter. You should get a block page, not the subreddit. Whether AdGuard's engine honors the `$all` document flag is the one unverified piece of the Chrome path; if the page loads, report it, because the fallback rule format is already designed.

## Part 4: NextDNS (covers every device, including phone apps)
1. Sign in at my.nextdns.io and open your profile.
2. **Parental Control** tab: enable the **Pornography** category. That covers the gif and tube sites wholesale.
3. **Denylist** tab: add `old.reddit.com` (kills the old-Reddit age click-through) and `redgifs.com` if the category missed it.
4. Confirm the NextDNS profile is actually installed on both the PC and the phone.

## Part 5: Living with the userscript
- **Allowed communities:** the `ALLOW` list at the top of the script (r/pornfree and r/nofap are pre-listed). To edit: Violentmonkey icon, Dashboard, click the script's edit symbol, change the list, Ctrl+S. Tampermonkey: icon, Dashboard, click the script name, edit, File then Save.
- **Console logging:** every allow or block decision is logged as `subgate: ...` with the layer that decided it. Press F12, Console tab, to see it. Once you trust the setup, set `VERBOSE` to `false` the same way you edit ALLOW.
- **Updates:** since v0.3.1 the workflow stamps your repo address into the script, so after installing it once from your repo, your userscript manager auto-updates it. If you installed an earlier version, reinstall once from the raw URL.

## Part 6: iPhone, honestly
Chrome on iOS has no extension platform, so neither the lists nor the userscript can run there. What protects the phone: the Part 1 account setting (covers the app and every browser) and Part 4 NextDNS. If you are willing to use Safari on the phone, the free AdGuard for iOS app can subscribe to your full list URL, and the Userscripts app can likely host subgate.user.js; both need an on-device test before trusting them.

## Part 7: The standalone extension (preview of what replaces Parts 2 and 3)
`extension/` contains the future of this project on desktop: one install that bundles the list engine, the click-time checks, the feed protection, and a settings page. It is in preview; keep Parts 2 and 3 running until it has proven itself.

To try it on Chrome: download the repo as a zip (green Code button, Download ZIP), extract it, go to `chrome://extensions`, turn on Developer mode, click **Load unpacked**, select the `extension` folder. On Firefox: `about:debugging`, **This Firefox**, **Load Temporary Add-on**, pick `extension/manifest.json` (Firefox forgets temporary add-ons on restart; the permanent path is the signed store version planned for v1). Then open the extension's options page, confirm the List URL points at your repo, and click **Update list now**. The status line should report your list size within seconds.

## Verify it works (three checks)
1. **Typed URL:** open a new tab, type a known blocked subreddit address, Enter. Expect uBlock's or AdGuard's block page.
2. **In-app click:** from Reddit search, click into a blocked community. Expect Reddit's own "you must be 18+" refusal (Part 1) or the dark "Blocked by subgate" page (userscript). The console line for a block reads `subgate: BLOCKED <name> layer: ...`.
3. **Feed:** browse r/popular. NSFW teasers and blurred thumbnails should simply not appear.

## What each part shows
- `subgate_full.txt` and `subgate_chrome.txt`: the published lists. Header comments show entry count and build time.
- `subgate_state.json`: the catalog of every verified name with status, subscribers, sources, timestamps. The workflow maintains it; never edit it.
- `subgate.user.js`: the in-browser layer. Installed once per desktop browser, self-updating after v0.3.1.
- `manual_seeds.txt`: paste any text containing subreddit names; the next run extracts and verifies them.
- `force_block.txt`: names that ship even without Reddit's flag.
- `sources.yaml`: provider, rate limits, caps, schedule, all commented. Its limits are guards; read HANDOFF.md before changing them.
- Each Actions run log prints a report line: confirmations, drain progress, list sizes, trims.

## Secrets and configuration
No secrets are required. `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USERNAME` exist only for the day Reddit approves API access, if ever; adding them switches verification to Reddit directly. Never commit keys.

## Version
Semver via git tags. Current: v0.4.0. The changelog lives in HANDOFF.md.
