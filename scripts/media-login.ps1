# Sign in to one media-route site for the visual ladder (studio/routelib): opens real Chrome on Video Studio's own profile for it.
#   scripts\media-login.ps1 meta        (sites: meta, chatgpt, bing, copilot, flow, marble)
# Sign in, accept the site's own first-run prompts, then CLOSE the window: two Chromes cannot share one profile, and a route
# fails while this window is open. Profiles live in <media_routes data>\profiles (default F:\videos_test\media_routes).
param([Parameter(Mandatory = $true)][ValidateSet('meta', 'chatgpt', 'bing', 'copilot', 'flow', 'marble')][string]$Site,
      [string]$Data = 'F:\videos_test\media_routes')
$ErrorActionPreference = 'Stop'
$Home_ = @{ meta = 'https://meta.ai/'; chatgpt = 'https://chatgpt.com/'; bing = 'https://www.bing.com/images/create';
            copilot = 'https://copilot.com/chat'; flow = 'https://flow.google.com/'; marble = 'https://marble.worldlabs.ai/' }
$Profile = Join-Path $Data "profiles\$Site"
New-Item -ItemType Directory -Force $Profile | Out-Null
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Chrome) { throw 'Google Chrome not found.' }
# no "Sign in to Chrome" first-run page, no Chrome sign-in / sync prompts, no "set as default" bar, no restore bubble
Start-Process -FilePath $Chrome -ArgumentList "--user-data-dir=`"$Profile`"", '--no-first-run', '--disable-sync', '--no-default-browser-check',
    '--hide-crash-restore-bubble', '--disable-features=SigninInterception,ChromeSigninInterception,ExplicitBrowserSigninUIOnDesktop',
    '--lang=en-US', '--window-position=120,80', '--window-size=1280,900', '--new-window', $Home_[$Site]
# (the automated runs park their window off-screen and Chrome remembers that per profile: the position above brings it back)
Write-Output "Chrome opened on $Profile. Sign in to $Site, then close the window."
