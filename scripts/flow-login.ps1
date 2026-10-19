# One-time setup for the Google Flow rung: opens Chrome with the dedicated Flow profile.
# Sign in to Google, open Flow once (accept its terms), then close Chrome. Video Studio reuses this profile.
# Close this Chrome window before running a job; two Chrome processes cannot share one profile.
$ErrorActionPreference = 'Stop'
$Profile = 'F:\videos_test\flow_profile'
New-Item -ItemType Directory -Force $Profile | Out-Null
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Chrome) { throw 'Google Chrome not found.' }
Start-Process -FilePath $Chrome -ArgumentList "--user-data-dir=`"$Profile`"", 'https://labs.google/fx/tools/flow'
Write-Output "Chrome opened with $Profile. Sign in, open Flow once, then close Chrome."
