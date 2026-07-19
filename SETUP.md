# subgate setup

Two ways to do this. Path A is one command. Path B is clicking, no installs. Both end in the same place.

Nothing here asks you for a token, and you should never paste a GitHub token into a chat window, a script, or a config file. The tools below send you to your own browser to sign in.

---

## Path A: one command (recommended)

**Windows PowerShell**

1. Extract the subgate zip, for example to `C:\Users\you\subgate`.
2. Install the two tools if you do not have them, in PowerShell:
   ```
   winget install Git.Git
   winget install GitHub.cli
   ```
   Close and reopen PowerShell afterward so it picks them up.
3. Go to the folder and run the script:
   ```
   cd C:\Users\you\subgate
   .\setup.ps1
   ```
   If Windows refuses to run it, do this once in the same window and try again:
   ```
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```
4. A browser window opens for GitHub sign-in. Choose GitHub.com, then HTTPS, then "Login with a web browser", and paste the short code it shows you.

**Git Bash, macOS, or Linux:** same thing, but run `bash setup.sh`.

The script creates the public repo, uploads the files, gives the workflow permission to save its own results, and starts the first run. It prints your three subscription URLs at the end.

---

## Path B: no installs, all in the browser

1. Go to github.com/new. Repository name: `subgate`. Visibility: **Public** (required, otherwise your ad blocker cannot fetch the lists). Do not add a README. Click Create repository.
2. On the next page click **uploading an existing file**.
3. Extract the zip on your PC, open the `subgate` folder, select everything inside it including the `.github` folder, and drag it all onto the upload area. Wait for the file list to finish appearing, then click **Commit changes**.
4. Confirm `.github/workflows/subgate.yml` is listed in the repo. If it is missing, the `.github` folder did not upload; drag just that folder in as a second upload.
5. Rename the ignore file: click `gitignore.txt`, click the pencil icon, change the filename box to `.gitignore`, then Commit changes. Optional, skip it if it gives you trouble.
6. Settings tab → Actions → General → Workflow permissions → select **Read and write permissions** → Save. Without this the run cannot save its results.
7. Actions tab → if it asks, click "I understand my workflows, go ahead and enable them" → click **subgate** in the left sidebar → **Run workflow** → set mode to **bootstrap** → **Run workflow**.

---

## After the first run

The core catalog lands within a few minutes; the directory crawl adds roughly half an hour. When the run shows a green check, three files exist in your repo: `subgate_full.txt`, `subgate_chrome.txt`, `subgate_state.json`.

Replace `OWNER` with your GitHub username in these:

- **Firefox:** uBlock Origin dashboard → Filter lists → Import → paste
  `https://raw.githubusercontent.com/OWNER/subgate/main/subgate_full.txt` → Apply changes.
- **Chrome:** AdGuard extension → Settings → Filters → Custom → Add → paste
  `https://raw.githubusercontent.com/OWNER/subgate/main/subgate_chrome.txt`.
- **Userscript, both browsers:** install Violentmonkey (Firefox) or Tampermonkey (Chrome), then open
  `https://raw.githubusercontent.com/OWNER/subgate/main/subgate.user.js` and accept the install prompt. On Chrome, turn on Developer mode at `chrome://extensions` first, or Tampermonkey will not run it.

From here it maintains itself: it runs every 6 hours and your ad blocker re-downloads the lists daily.

---

## When something goes wrong

**"Run workflow" button is missing.** The workflow file is not on the default branch. Check that `.github/workflows/subgate.yml` exists in the repo, spelled exactly that way.

**Run fails with a permissions or 403 error on the commit step.** Settings → Actions → General → Workflow permissions → Read and write permissions → Save, then re-run.

**Actions tab shows nothing.** Actions are disabled for the repo. Settings → Actions → General → Allow all actions.

**The raw list URLs return 404.** Normal until the first run finishes and commits the files. Also check the branch in the URL is `main`.

**AdGuard complains about too many rules.** Lower `chrome_max_rules` in `sources.yaml`, commit, and the next run emits a smaller Chrome list.

**A safe subreddit gets blocked by the userscript.** Add its name to the `ALLOW` list at the top of `subgate.user.js`. The browser console logs every decision with its reason, so that line tells you which rule fired.

**Nothing runs on schedule.** GitHub pauses scheduled workflows in repos with no activity for 60 days. Push any commit to wake it up.
