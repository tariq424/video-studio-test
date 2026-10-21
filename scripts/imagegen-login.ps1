# Opens Chrome with the Google profile that the Gemini image rung (imagegen.py) and the Flow rung share
# (F:\videos_test\flow_profile), at Gemini or Flow. Use it to sign in, or to clear a check Gemini shows. Then close Chrome:
# two Chrome processes cannot share one profile, so close this window before running a job.
#   powershell -ExecutionPolicy Bypass -File scripts\imagegen-login.ps1 -Site gemini     (gemini | flow)
param([ValidateSet('gemini', 'flow')][string]$Site = 'gemini')
$ErrorActionPreference = 'Stop'
$Urls = @{ gemini = 'https://gemini.google.com/app'; flow = 'https://labs.google/fx/tools/flow' }
$Profile = 'F:\videos_test\flow_profile'
New-Item -ItemType Directory -Force $Profile | Out-Null
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Chrome) { throw 'Google Chrome not found.' }
Start-Process -FilePath $Chrome -ArgumentList "--user-data-dir=`"$Profile`"", $Urls[$Site]
Write-Output "Chrome opened with $Profile at $Site. Sign in if asked, then close Chrome."
