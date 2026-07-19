#!/usr/bin/env bash
# subgate setup for Git Bash, macOS, or Linux. The PowerShell twin is setup.ps1.
#
# Run it from inside the extracted subgate folder:
#   bash setup.sh
#
# You authenticate in your own browser. This script never asks you for a token
# and never stores one.

set -euo pipefail
REPO_NAME="subgate"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo ""
    echo "Missing: $1"
    echo "Install it with:  $2"
    echo "Then run this script again."
    exit 1
  fi
}

echo "subgate setup"
echo ""

need git "winget install Git.Git   (or: brew install git)"
need gh  "winget install GitHub.cli   (or: brew install gh)"

# Step 1: sign in to GitHub in your browser if not already signed in.
if ! gh auth status >/dev/null 2>&1; then
  echo "Signing in to GitHub. Your browser will open."
  echo "Choose: GitHub.com, then HTTPS, then Login with a web browser."
  gh auth login
fi

USER_LOGIN="$(gh api user --jq .login)"
echo "Signed in as $USER_LOGIN"

# Step 2: the ignore file has to be named .gitignore in the repo.
if [ -f gitignore.txt ] && [ ! -f .gitignore ]; then
  mv gitignore.txt .gitignore
  echo "Renamed gitignore.txt to .gitignore"
fi

# Step 3: make this folder a git repo and commit everything.
[ -d .git ] || git init >/dev/null
git branch -M main
git add -A
git commit -m "subgate: initial commit" --allow-empty >/dev/null

# Step 4: create the repo on GitHub and push. Public is required so your ad
# blocker can fetch the list URLs without logging in.
if gh repo view "$USER_LOGIN/$REPO_NAME" >/dev/null 2>&1; then
  echo "Repo $USER_LOGIN/$REPO_NAME already exists, pushing to it."
  git remote remove origin >/dev/null 2>&1 || true
  git remote add origin "https://github.com/$USER_LOGIN/$REPO_NAME.git"
  git push -u origin main --force
else
  gh repo create "$REPO_NAME" --public --source=. --remote=origin --push
fi

# Step 5: allow the workflow to commit the catalog and lists back to the repo.
gh api -X PUT "/repos/$USER_LOGIN/$REPO_NAME/actions/permissions/workflow" \
  -f default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=false >/dev/null
echo "Workflow write permission enabled"

# Step 6: start the first run.
echo "Starting the bootstrap run..."
sleep 3
gh workflow run subgate.yml -f mode=bootstrap

cat <<EOF

Done. The first run is going now.
Watch it live:   gh run watch
Or in a browser: https://github.com/$USER_LOGIN/$REPO_NAME/actions

When it finishes, subscribe your browsers to these URLs:
  Firefox uBlock Origin:
    https://raw.githubusercontent.com/$USER_LOGIN/$REPO_NAME/main/subgate_full.txt
  Chrome AdGuard:
    https://raw.githubusercontent.com/$USER_LOGIN/$REPO_NAME/main/subgate_chrome.txt
  Userscript, install in both browsers:
    https://raw.githubusercontent.com/$USER_LOGIN/$REPO_NAME/main/subgate.user.js
EOF
