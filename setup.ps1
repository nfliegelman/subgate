# subgate setup for Windows PowerShell.
#
# What this does: creates the public GitHub repo, uploads these files, makes
# sure the workflow is allowed to commit its own results, and starts the first
# bootstrap run. About one minute of your attention.
#
# How to run it:
#   1. Extract the subgate zip somewhere, for example C:\Users\you\subgate
#   2. Open PowerShell, then: cd C:\Users\you\subgate
#   3. Run: .\setup.ps1
#
# If Windows blocks the script, run this once in the same window:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# You will authenticate in your own browser. This script never asks you for a
# token and never stores one.

$ErrorActionPreference = "Stop"
$RepoName = "subgate"

function Need($cmd, $installHint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "Missing: $cmd" -ForegroundColor Yellow
        Write-Host "Install it with:  $installHint"
        Write-Host "Then run this script again."
        exit 1
    }
}

Write-Host "subgate setup" -ForegroundColor Cyan
Write-Host ""

Need "git" "winget install Git.Git"
Need "gh"  "winget install GitHub.cli"

# Step 1: sign in to GitHub in your browser if not already signed in.
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Signing in to GitHub. Your browser will open." -ForegroundColor Cyan
    Write-Host "Choose: GitHub.com, then HTTPS, then Login with a web browser."
    gh auth login
}

$User = (gh api user --jq .login)
Write-Host "Signed in as $User" -ForegroundColor Green

# Step 2: the ignore file has to be named .gitignore in the repo.
if ((Test-Path "gitignore.txt") -and (-not (Test-Path ".gitignore"))) {
    Move-Item "gitignore.txt" ".gitignore"
    Write-Host "Renamed gitignore.txt to .gitignore"
}

# Step 3: make this folder a git repo and commit everything.
if (-not (Test-Path ".git")) { git init | Out-Null }
git branch -M main
git add -A
git commit -m "subgate: initial commit" --allow-empty | Out-Null

# Step 4: create the repo on GitHub and push. Public is required so your ad
# blocker can fetch the list URLs without logging in.
$exists = $false
gh repo view "$User/$RepoName" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { $exists = $true }

if ($exists) {
    Write-Host "Repo $User/$RepoName already exists, pushing to it."
    git remote remove origin 2>$null | Out-Null
    git remote add origin "https://github.com/$User/$RepoName.git"
    git push -u origin main --force
} else {
    gh repo create $RepoName --public --source=. --remote=origin --push
}

# Step 5: allow the workflow to commit the catalog and lists back to the repo.
gh api -X PUT "/repos/$User/$RepoName/actions/permissions/workflow" `
    -f default_workflow_permissions=write `
    -F can_approve_pull_request_reviews=false | Out-Null
Write-Host "Workflow write permission enabled" -ForegroundColor Green

# Step 6: start the first run.
Write-Host "Starting the bootstrap run..." -ForegroundColor Cyan
Start-Sleep -Seconds 3
gh workflow run subgate.yml -f mode=bootstrap

Write-Host ""
Write-Host "Done. The first run is going now." -ForegroundColor Green
Write-Host "Watch it live:   gh run watch"
Write-Host "Or in a browser: https://github.com/$User/$RepoName/actions"
Write-Host ""
Write-Host "When it finishes, subscribe your browsers to these URLs:"
Write-Host "  Firefox uBlock Origin:"
Write-Host "    https://raw.githubusercontent.com/$User/$RepoName/main/subgate_full.txt"
Write-Host "  Chrome AdGuard:"
Write-Host "    https://raw.githubusercontent.com/$User/$RepoName/main/subgate_chrome.txt"
Write-Host "  Userscript, install in both browsers:"
Write-Host "    https://raw.githubusercontent.com/$User/$RepoName/main/subgate.user.js"
