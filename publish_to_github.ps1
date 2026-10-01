# Publish F:\code\explainer-studio to a PRIVATE GitHub repo.
# Run in PowerShell:  cd F:\code\explainer-studio ; .\publish_to_github.ps1
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { winget install --id Git.Git -e --source winget; Write-Host "Git installed. Close and reopen PowerShell, then run this script again."; exit }
if (-not (Get-Command gh  -ErrorAction SilentlyContinue)) { winget install --id GitHub.cli -e --source winget; Write-Host "GitHub CLI installed. Close and reopen PowerShell, then run this script again."; exit }
# One-time browser login (handles 2FA). Skipped if already logged in.
gh auth status 2>$null; if ($LASTEXITCODE -ne 0) { gh auth login --hostname github.com --git-protocol https --web }
gh auth setup-git
if (-not (Test-Path .git)) {
  git init -b main
  git config user.name "Tariq"
  git config user.email "tarrigg@gmail.com"
}
git add -A
# safety: refuse if secrets got staged
$staged = git diff --cached --name-only
if ($staged -match '(^|/)\.env$' -or $staged -match 'settings\.json') { throw "Secret file staged - aborting." }
git commit -m "Explainer Studio: initial import" 2>$null
gh repo view explainer-studio 2>$null
if ($LASTEXITCODE -ne 0) { gh repo create explainer-studio --private --source . --remote origin --push }
else { git push -u origin main }
gh repo view explainer-studio --web
