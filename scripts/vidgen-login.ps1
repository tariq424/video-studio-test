# One-time setup for a free AI video generator rung (vidgen.py): opens Chrome with that site's own profile.
# Sign in, make one video by hand if the site asks you to accept terms, then close Chrome. Video Studio reuses the profile.
# Close this Chrome window before running a job; two Chrome processes cannot share one profile.
#   powershell -ExecutionPolicy Bypass -File scripts\vidgen-login.ps1 -Site meta     (meta | bing | sora | flow)
param([ValidateSet('meta', 'bing', 'sora', 'flow')][string]$Site = 'meta')
$ErrorActionPreference = 'Stop'
$Urls = @{ meta = 'https://www.meta.ai/'; bing = 'https://www.bing.com/images/create?ctype=video';
           sora = 'https://sora.chatgpt.com/'; flow = 'https://labs.google/fx/tools/flow' }
$Profile = "F:\videos_test\${Site}_profile"
New-Item -ItemType Directory -Force $Profile | Out-Null
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Chrome) { throw 'Google Chrome not found.' }
Start-Process -FilePath $Chrome -ArgumentList "--user-data-dir=`"$Profile`"", $Urls[$Site]
Write-Output "Chrome opened with $Profile. Sign in to $Site, then close Chrome."
