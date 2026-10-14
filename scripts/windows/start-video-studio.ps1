<#
Starts Pinokio, Ollama, WanGP UI/MCP, Video Studio, and opens Opera.
Launcher pages are opened through POST /pinokio/open; readiness is verified.
WanGP ports come from Pinokio runtime local.url and local.mcp_url, not guesses.
Every fixed port is checked before launches. Conflict exit code 4; WanGP failure 5.
Existing Ollama warning behavior and Opera step retained. No running jobs restarted.
All paths are absolute or resolved from config/PSScriptRoot for Task Scheduler.
Log: F:\scripts\logs\start-video-studio.log. WaitForWanGP defaults to 300 seconds.
#>
param(
    [int]$WaitForPinokio = 0,
    [switch]$NoLaunchPinokio,
    [switch]$NoLaunchOllama,
    [switch]$NoBrowser,
    [int]$WaitForWanGP = 300,
    [string]$LogDir = 'F:\scripts\logs'
)

$ErrorActionPreference = 'Stop'
if (-not [IO.Path]::IsPathRooted($LogDir)) { $LogDir = Join-Path $PSScriptRoot $LogDir }
$ProgressPreference = 'SilentlyContinue'

$Pinokio  = 'http://127.0.0.1:42000'
$Ollama   = 'http://127.0.0.1:11434'
$Studio   = 'http://127.0.0.1:42020'
$Status   = "$Studio/api/status"
$OllamaHealth = "$Ollama/api/tags"
# Launcher paths are resolved through Pinokio's runtime API.

# Candidate locations for Pinokio exe. Add yours if the search misses it.
$PinokioExePaths = @(
    "$env:LOCALAPPDATA\Programs\Pinokio\Pinokio.exe",
    "$env:LOCALAPPDATA\Programs\pinokio\Pinokio.exe",
    "$env:LOCALAPPDATA\Pinokio\Pinokio.exe",
    "$env:APPDATA\Pinokio\Pinokio.exe",
    "$env:ProgramFiles\Pinokio\Pinokio.exe",
    "${env:ProgramFiles(x86)}\Pinokio\Pinokio.exe"
)

# Candidate locations for Ollama exe. Both "ollama app.exe" (tray) and "ollama.exe" (CLI/server) can work.
# "ollama app.exe" is the desktop tray launcher — preferred, since it starts the background server.
$OllamaExePaths = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe",
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "$env:LOCALAPPDATA\Programs\ollama\ollama app.exe",
    "$env:ProgramFiles\Ollama\ollama app.exe",
    "$env:ProgramFiles\Ollama\ollama.exe",
    "${env:ProgramFiles(x86)}\Ollama\ollama app.exe",
    "${env:ProgramFiles(x86)}\Ollama\ollama.exe"
)

$LogFile = $null
try { New-Item -ItemType Directory -Force -Path $LogDir -ErrorAction Stop | Out-Null; $LogFile = Join-Path $LogDir 'start-video-studio.log' } catch {}

function Say([string]$msg, [string]$color = 'Gray') {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg
    Write-Host $line -ForegroundColor $color
    if ($LogFile) { try { Add-Content -Path $LogFile -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd'), $line) } catch {} }
}

function Test-Http([string]$url, [int]$timeout = 5, [switch]$AnyStatus) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeout -MaximumRedirection 0 -ErrorAction Stop
        return ($AnyStatus -or $r.StatusCode -eq 200)
    } catch {
        if ($AnyStatus -and $_.Exception.Response) { return $true }
        return $false
    }
}

function Find-Opera {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Opera\opera.exe",
        "$env:LOCALAPPDATA\Programs\Opera\launcher.exe",
        "$env:ProgramFiles\Opera\opera.exe",
        "$env:ProgramFiles\Opera\launcher.exe",
        "${env:ProgramFiles(x86)}\Opera\opera.exe",
        "${env:ProgramFiles(x86)}\Opera\launcher.exe"
    )
    foreach ($p in $candidates) { if ($p -and (Test-Path $p)) { return $p } }
    return $null
}

function Find-PinokioExe {
    foreach ($p in $PinokioExePaths) { if ($p -and (Test-Path $p)) { return $p } }
    $searchRoot = "$env:LOCALAPPDATA\Programs"
    if (Test-Path $searchRoot) {
        try {
            $hit = Get-ChildItem -Path $searchRoot -Filter 'pinokio*.exe' -Recurse -Depth 3 -File -ErrorAction SilentlyContinue |
                   Select-Object -First 1
            if ($hit) { return $hit.FullName }
        } catch {}
    }
    return $null
}

function Find-OllamaExe {
    foreach ($p in $OllamaExePaths) { if ($p -and (Test-Path $p)) { return $p } }
    $searchRoot = "$env:LOCALAPPDATA\Programs"
    if (Test-Path $searchRoot) {
        try {
            $hit = Get-ChildItem -Path $searchRoot -Filter 'ollama*.exe' -Recurse -Depth 3 -File -ErrorAction SilentlyContinue |
                   Where-Object { $_.Name -match 'ollama( app)?\.exe' } |
                   Select-Object -First 1
            if ($hit) { return $hit.FullName }
        } catch {}
    }
    return $null
}

function Start-Pinokio {
    $exe = Find-PinokioExe
    if (-not $exe) {
        Say 'Pinokio exe not found. Searched:' 'Red'
        foreach ($p in $PinokioExePaths) { Say "  $p" 'Red' }
        Say "  $env:LOCALAPPDATA\Programs (recursive, depth 3, pinokio*.exe)" 'Red'
        Say 'Fix: right-click the Pinokio shortcut, open Properties, copy Target path,' 'Red'
        Say 'then add it to $PinokioExePaths near the top of this script.' 'Red'
        return $false
    }
    Say "Launching Pinokio: $exe" 'Yellow'
    try { Start-Process -FilePath $exe -WindowStyle Hidden -WorkingDirectory (Split-Path $exe -Parent) -ErrorAction Stop }
    catch { Say ("Failed to launch Pinokio: {0}" -f $_.Exception.Message) 'Red'; return $false }

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if (Test-Http "$Pinokio/" 3 -AnyStatus) { Say 'Pinokio started.' 'Green'; return $true }
    }
    Say 'Pinokio did not come up within 60 seconds.' 'Red'
    return $false
}

function Start-Ollama {
    $exe = Find-OllamaExe
    if (-not $exe) {
        Say 'Ollama exe not found. Searched:' 'Yellow'
        foreach ($p in $OllamaExePaths) { Say "  $p" 'Yellow' }
        Say "  $env:LOCALAPPDATA\Programs (recursive, depth 3, ollama*.exe)" 'Yellow'
        Say 'Fix: right-click the Ollama shortcut, open Properties, copy Target path,' 'Yellow'
        Say 'then add it to $OllamaExePaths near the top of this script.' 'Yellow'
        Say 'Continuing without Ollama. Pipeline jobs that need vision checks will fail.' 'Yellow'
        return $false
    }
    Say "Launching Ollama: $exe" 'Yellow'
    try { Start-Process -FilePath $exe -WindowStyle Hidden -WorkingDirectory (Split-Path $exe -Parent) -ErrorAction Stop }
    catch { Say ("Failed to launch Ollama: {0}" -f $_.Exception.Message) 'Yellow'; return $false }

    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if (Test-Http $OllamaHealth 3) { Say 'Ollama started.' 'Green'; return $true }
    }
    Say 'Ollama did not respond on http://127.0.0.1:11434 within 45 seconds.' 'Yellow'
    Say 'Continuing anyway. Vision checks may fail until Ollama is running.' 'Yellow'
    return $false
}

function Get-AppState([string]$app) {
    try {
        $ref = [Uri]::EscapeDataString("pinokio://127.0.0.1:42000/api/$app")
        return Invoke-RestMethod "$Pinokio/pinokio/resource/status?ref=$ref" -TimeoutSec 5
    } catch { return $null }
}

function Start-PinokioPage([string]$app) {
    # Tested: POST /api/... is 404; GET renders HTML without running it.
    # Pinokio's supported HTTP open API loads that HTML in a real browser,
    # which triggers its start logic. No hand-built WebSocket messages.
    $url = "$Pinokio/api/$app/start.js"
    $body = @{url=$url; surface='browser'} | ConvertTo-Json -Compress
    $r = Invoke-RestMethod "$Pinokio/pinokio/open" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 15
    if (-not $r.success) { throw "Pinokio could not open launcher: $url" }
}

function Test-Service([string]$name, [string]$url) {
    try {
        switch ($name) {
            'Pinokio' { $r = Invoke-RestMethod "$Pinokio/pinokio/home" -TimeoutSec 4; return [bool]$r.path }
            'Ollama' { $r = Invoke-RestMethod $OllamaHealth -TimeoutSec 4; return ($null -ne $r.models) }
            'Studio' { $r = Invoke-RestMethod $Status -TimeoutSec 4; return ($null -ne $r.stages) }
            'WanUI' { $r = Invoke-WebRequest "$($url.TrimEnd('/'))/config" -UseBasicParsing -TimeoutSec 5; return ($r.Content -match '"components"' -and $r.Content -match 'Wan.*GP') }
            'WanMCP' {
                $body = @{jsonrpc='2.0';id=1;method='initialize';params=@{protocolVersion='2025-03-26';capabilities=@{};clientInfo=@{name='startup-health';version='1'}}} | ConvertTo-Json -Depth 5 -Compress
                $r = Invoke-WebRequest $url -Method Post -ContentType 'application/json' -Headers @{Accept='application/json, text/event-stream'} -Body $body -UseBasicParsing -TimeoutSec 8
                $ok = ($r.Content -match '"protocolVersion"' -and $r.Content -match '"name"\s*:\s*"WanGP"')
                $session = $r.Headers['Mcp-Session-Id']
                if ($session) {
                    try { Invoke-WebRequest $url -Method Delete -Headers @{'Mcp-Session-Id'=[string]$session;Accept='application/json, text/event-stream'} -UseBasicParsing -TimeoutSec 3 | Out-Null } catch {}
                }
                return $ok
            }
        }
    } catch { return $false }
    return $false
}

function Assert-Port([int]$port, [string]$service, [string]$url) {
    $owners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -eq 0) { return }
    if (Test-Service $service $url) { return }
    foreach ($ownerId in $owners) {
        $proc = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
        # 42009 is an installed Pinokio Caddy proxy, not WanGP's fixed UI port.
        # It can legitimately have no upstream while an app is stopped.
        if ($port -eq 42009 -and $proc.Path -eq (Join-Path $PinokioHome 'bin\miniforge\Library\bin\caddy.exe') -and (Test-Service 'Pinokio' '')) {
            Say "Port 42009 belongs to Pinokio's managed proxy (PID $ownerId); WanGP uses its runtime URL."
            continue
        }
        Say "PORT CONFLICT: port $port held by PID $ownerId ($($proc.ProcessName), $($proc.Path)); expected $service is not responding. Exiting without killing it." 'Red'
        exit 4
    }
}

function Get-WanUrls {
    $state = Get-AppState 'wan.git'
    $urls = @{ui=$null; mcp=$null; running=$false}
    if ($state) {
        $urls.running = $state.running
        foreach ($entry in $state.local_entries) {
            if ($entry.local.url) { $urls.ui = [string]$entry.local.url }
            if ($entry.local.mcp_url) { $urls.mcp = [string]$entry.local.mcp_url }
        }
    }
    return $urls
}

function Wait-Wan {
    $deadline = (Get-Date).AddSeconds($WaitForWanGP)
    do {
        $urls = Get-WanUrls
        if ($urls.ui -and $urls.mcp -and (Test-Service 'WanUI' $urls.ui) -and (Test-Service 'WanMCP' $urls.mcp)) {
            Say "WanGP healthy: UI $($urls.ui); MCP $($urls.mcp)" 'Green'
            return $true
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    Say "WanGP UI/MCP did not become healthy within $WaitForWanGP seconds. See Pinokio wan.git/start.js logs." 'Red'
    return $false
}

# Resolve Pinokio's real home, independently of Task Scheduler's current directory.
$PinokioHome = $null
$configPath = Join-Path $env:USERPROFILE '.pinokio\config.json'
if (Test-Path -LiteralPath $configPath) {
    $PinokioHome = (Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).home
}
if (-not $PinokioHome) {
    try { $PinokioHome = (Invoke-RestMethod "$Pinokio/pinokio/home" -TimeoutSec 3).path } catch {}
}
if (-not $PinokioHome) { Say 'Cannot resolve Pinokio home from config or control plane.' 'Red'; exit 1 }
$PinokioHome = [IO.Path]::GetFullPath($PinokioHome)
$WanApp = Join-Path $PinokioHome 'api\wan.git\app'
if (-not (Test-Path -LiteralPath (Join-Path $WanApp 'wgp.py'))) { Say "WanGP installation not found at $WanApp" 'Red'; exit 5 }
Say "WanGP installation: $WanApp (launcher-managed Python, not a standalone exe)."

# Check every requested port BEFORE starting any service.
Assert-Port 42000 'Pinokio' ''
Assert-Port 42020 'Studio' ''
Assert-Port 11434 'Ollama' ''
Assert-Port 8000 'WanMCP' 'http://127.0.0.1:8000/mcp'
Assert-Port 42009 'WanUI' 'http://127.0.0.1:42009'

Say '== Start Video Studio Stack ==' 'Cyan'

# --- 1. Pinokio ---
Say "Checking Pinokio at $Pinokio ..."
$pinokioUp = Test-Http "$Pinokio/" 5 -AnyStatus

if (-not $pinokioUp -and $WaitForPinokio -gt 0) {
    Say "Waiting up to $WaitForPinokio s for Pinokio to come up on its own..."
    $deadline = (Get-Date).AddSeconds($WaitForPinokio)
    while (-not $pinokioUp -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        $pinokioUp = Test-Http "$Pinokio/" 3 -AnyStatus
    }
}

if (-not $pinokioUp -and -not $NoLaunchPinokio) {
    Say 'Pinokio is not running. Launching it...' 'Yellow'
    $pinokioUp = Start-Pinokio
}

if (-not $pinokioUp) {
    Say 'Pinokio is not running and could not be started. Exiting.' 'Red'
    exit 1
}
Say 'Pinokio is running.' 'Green'

# --- 2. Ollama ---
Say "Checking Ollama at $OllamaHealth ..."
$ollamaUp = Test-Http $OllamaHealth 5

if (-not $ollamaUp -and -not $NoLaunchOllama) {
    Say 'Ollama is not running. Launching it...' 'Yellow'
    $ollamaUp = Start-Ollama
}

if ($ollamaUp) {
    Say 'Ollama is running.' 'Green'
} else {
    Say 'Ollama is NOT running. Pipeline jobs that need vision checks will fail until it starts.' 'Yellow'
}

# --- 3. WanGP UI + MCP ---
$wan = Get-WanUrls
if (-not ($wan.ui -and $wan.mcp -and (Test-Service 'WanUI' $wan.ui) -and (Test-Service 'WanMCP' $wan.mcp))) {
    if (-not $wan.running) {
        Say 'WanGP is not running. Opening its Pinokio launcher...' 'Yellow'
        try { Start-PinokioPage 'wan.git' } catch { Say $_.Exception.Message 'Red'; exit 5 }
    } else { Say 'WanGP launcher is already running; waiting for UI and MCP.' }
    if (-not (Wait-Wan)) { exit 5 }
} else { Say "WanGP already healthy: $($wan.ui); $($wan.mcp)" 'Green' }

# --- 4. Video Studio already up? ---
Say "Checking Video Studio at $Status ..."
if (Test-Http $Status 10) {
    Say 'Video Studio is already running - not starting it again.' 'Green'
} else {
    # --- 4. Start it through Pinokio ---
    Say 'Video Studio is not running. Asking Pinokio to run video-studio/start.js ...' 'Yellow'
    try { Start-PinokioPage 'video-studio' }
    catch {
        Say ("Start failed: could not open the launcher page to Pinokio ({0})." -f $_.Exception.Message) 'Red'
        Say "Open $Pinokio/api/video-studio/start.js in a browser to start it by hand." 'Red'
        exit 2
    }
    Say 'Start request sent. Waiting for Video Studio (up to 90 s) ...'

    # --- 5. Poll ---
    $up = $false
    for ($i = 1; $i -le 30; $i++) {
        Start-Sleep -Seconds 3
        if (Test-Http $Status 5) { $up = $true; break }
        if ($i % 5 -eq 0) { Say ("  still waiting ({0} s)" -f ($i * 3)) }
    }
    if (-not $up) {
        Say "Video Studio did not come up within 90 seconds. Check its terminal in Pinokio ($Pinokio/api/video-studio/start.js)." 'Red'
        exit 3
    }
    Say 'Video Studio answered /api/status.' 'Green'
}

# --- 6. Browser ---
if (-not $NoBrowser) {
    $opera = Find-Opera
    if ($opera) {
        Say "Opening $Studio in Opera ..."
        Start-Process -FilePath $opera -ArgumentList $Studio -WindowStyle Hidden
    } else {
        Say "Opera not found (checked LOCALAPPDATA, Program Files, Program Files (x86)). Open $Studio yourself." 'Yellow'
    }
}

# --- 7. Done ---
Say "Video Studio is up at $Studio" 'Green'
exit 0