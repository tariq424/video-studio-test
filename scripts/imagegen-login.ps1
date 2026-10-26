# Opens a browser with one of the image-generator profiles, so you can sign in once (or clear a check a site shows).
#   gemini | flow : Chrome, F:\videos_test\flow_profile (the Google profile the Gemini image rung and Flow share)
#   chatgpt       : Chrome, F:\videos_test\chatgpt_profile
#   bing          : Microsoft Edge, F:\videos_test\bing_profile (separate from your everyday Edge profile)
#   marble        : Chrome, F:\videos_test\marble_profile (World Labs Marble: recreated scenes, the ladder's last rung, on demand)
#   m365          : Chrome, F:\videos_test\m365_profile (Microsoft 365 account: Bing search for QC-repair research, the 365 apps)
# Then close the window: a profile can't be used by two browsers at once, so close it before a job runs.
#   powershell -ExecutionPolicy Bypass -File scripts\imagegen-login.ps1 -Site chatgpt
param([ValidateSet('gemini', 'flow', 'chatgpt', 'bing', 'marble', 'm365')][string]$Site = 'gemini')
$ErrorActionPreference = 'Stop'
$Urls = @{ gemini = 'https://gemini.google.com/app'; flow = 'https://labs.google/fx/tools/flow'
           chatgpt = 'https://chatgpt.com/auth/login'; bing = 'https://www.bing.com/images/create'; marble = 'https://marble.worldlabs.ai/'; m365 = 'https://www.microsoft365.com/' }
$Profiles = @{ gemini = 'F:\videos_test\flow_profile'; flow = 'F:\videos_test\flow_profile'
               chatgpt = 'F:\videos_test\chatgpt_profile'; bing = 'F:\videos_test\bing_profile'; marble = 'F:\videos_test\marble_profile'; m365 = 'F:\videos_test\m365_profile' }
$Profile = $Profiles[$Site]
New-Item -ItemType Directory -Force $Profile | Out-Null
if ($Site -eq 'bing') {
    $Browser = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
               Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Browser) { throw 'Microsoft Edge not found.' }
} else {
    $Browser = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
                 "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Browser) { throw 'Google Chrome not found.' }
}
Start-Process -FilePath $Browser -ArgumentList "--user-data-dir=`"$Profile`"", "--no-first-run", "--new-window", $Urls[$Site]
Write-Output "$Site opened ($Browser) with $Profile. Sign in if asked, then close the window."
