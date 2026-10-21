# One-time setup for a free image generator rung (imagegen.py) or Flow: opens Chrome with that site's own profile.
# Sign in, make one image by hand if the site asks you to accept terms, then close Chrome. Video Studio reuses the profile.
# Close this Chrome window before running a job; two Chrome processes cannot share one profile.
#   powershell -ExecutionPolicy Bypass -File scripts\imagegen-login.ps1 -Site meta     (bing | meta | flow)
param([ValidateSet('bing', 'meta', 'flow')][string]$Site = 'bing')
$ErrorActionPreference = 'Stop'
$Urls = @{ bing = 'https://www.bing.com/images/create'; meta = 'https://www.meta.ai/'; flow = 'https://labs.google/fx/tools/flow' }
$Profile = "F:\videos_test\${Site}_profile"
New-Item -ItemType Directory -Force $Profile | Out-Null
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Chrome) { throw 'Google Chrome not found.' }
Start-Process -FilePath $Chrome -ArgumentList "--user-data-dir=`"$Profile`"", $Urls[$Site]
Write-Output "Chrome opened with $Profile. Sign in to $Site, then close Chrome."
