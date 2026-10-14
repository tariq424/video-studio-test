<#
.SYNOPSIS
  Start Video Studio (Pinokio app "video-studio") and open it in Opera. Safe to run any time.

.DESCRIPTION
  1. Checks Pinokio is running at http://127.0.0.1:42000 (optionally waits for it: -WaitForPinokio <seconds>).
  2. Checks Video Studio at http://127.0.0.1:42020/api/status. Already up -> step 5.
  3. Asks Pinokio to run video-studio/start.js.
     Pinokio has no plain HTTP "start" endpoint: GET /api/video-studio/start.js only renders the terminal page, and the page
     starts the script over Pinokio's WebSocket. This script sends that same WebSocket message ({"uri": "~/api/video-studio/start.js"}).
     Pinokio runs it only if it isn't already running, so this never starts a second copy.
  4. Polls /api/status every 3 s for up to 90 s.
  5. Opens http://127.0.0.1:42020 in Opera (or prints the URL if Opera isn't installed).

  It never stops or restarts Video Studio, so a running job is never interrupted.

.PARAMETER WaitForPinokio
  Seconds to wait for Pinokio to come up before giving up (0 = check once). The logon task uses 180.

.PARAMETER NoBrowser
  Don't open Opera.

.NOTES
  Exit codes: 0 ok (also when Opera wasn't found: that's reported, not fatal), 1 Pinokio not running, 2 start failed,
  3 Video Studio didn't answer within 90 s. Log: F:\scripts\logs\start-video-studio.log
#>
param(
    [int]$WaitForPinokio = 0,
    [switch]$NoBrowser,
    [string]$LogDir = 'F:\scripts\logs'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is much faster without the progress bar

$Pinokio  = 'http://127.0.0.1:42000'
$Studio   = 'http://127.0.0.1:42020'
$Status   = "$Studio/api/status"
$ScriptUri = '~/api/video-studio/start.js'

$LogFile = $null   # logging is best effort: a missing drive never stops the script
try { New-Item -ItemType Directory -Force -Path $LogDir -ErrorAction Stop | Out-Null; $LogFile = Join-Path $LogDir 'start-video-studio.log' } catch {}

function Say([string]$msg, [string]$color = 'Gray') {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg
    Write-Host $line -ForegroundColor $color
    if ($LogFile) { try { Add-Content -Path $LogFile -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd'), $line) } catch {} }
}

function Test-Http([string]$url, [int]$timeout = 5, [switch]$AnyStatus) {
    # $true when the server answers. -AnyStatus: any HTTP status counts (the server is up); otherwise only 200.
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeout -MaximumRedirection 0 -ErrorAction Stop
        return ($AnyStatus -or $r.StatusCode -eq 200)
    } catch {
        if ($AnyStatus -and $_.Exception.Response) { return $true }   # 3xx/4xx/5xx: something is listening
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

function Start-ViaPinokio {
    # Same message Pinokio's own terminal page sends when you click the app: run start.js unless it's already running.
    $ws = New-Object System.Net.WebSockets.ClientWebSocket
    $cts = New-Object System.Threading.CancellationTokenSource
    $cts.CancelAfter([TimeSpan]::FromSeconds(20))
    $ws.Options.SetRequestHeader('Origin', $Pinokio)
    $ws.ConnectAsync([Uri]'ws://127.0.0.1:42000', $cts.Token).GetAwaiter().GetResult() | Out-Null
    $payload = @{ uri = $ScriptUri; client = @{ cols = 120; rows = 30 } } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $seg = New-Object System.ArraySegment[byte] -ArgumentList (, $bytes)
    $ws.SendAsync($seg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).GetAwaiter().GetResult() | Out-Null
    # read a little of the terminal stream so Pinokio has picked the request up before we disconnect
    $buf = New-Object byte[] 8192
    $deadline = (Get-Date).AddSeconds(4)
    while ((Get-Date) -lt $deadline -and $ws.State -eq 'Open') {
        $rseg = New-Object System.ArraySegment[byte] -ArgumentList (, $buf)
        $t = $ws.ReceiveAsync($rseg, $cts.Token)
        if (-not $t.Wait(1500)) { break }
    }
    try { $ws.CloseOutputAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', [Threading.CancellationToken]::None).Wait(2000) | Out-Null } catch {}
    $ws.Dispose()
}

Say '== Start Video Studio ==' 'Cyan'

# 1. Pinokio
Say "Checking Pinokio at $Pinokio ..."
$deadline = (Get-Date).AddSeconds([Math]::Max(0, $WaitForPinokio))
$pinokioUp = Test-Http "$Pinokio/" 5 -AnyStatus
while (-not $pinokioUp -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $pinokioUp = Test-Http "$Pinokio/" 5 -AnyStatus
}
if (-not $pinokioUp) {
    Say 'Pinokio is not running. Start it first.' 'Red'
    exit 1
}
Say 'Pinokio is running.' 'Green'

# 2. Already up?
Say "Checking Video Studio at $Status ..."
if (Test-Http $Status 10) {
    Say 'Video Studio is already running - not starting it again.' 'Green'
} else {
    # 3. Start it through Pinokio
    Say 'Video Studio is not running. Asking Pinokio to run video-studio/start.js ...' 'Yellow'
    try { Start-ViaPinokio }
    catch {
        Say ("Start failed: could not send the start request to Pinokio ({0})." -f $_.Exception.Message) 'Red'
        Say "Open $Pinokio/api/video-studio/start.js in a browser to start it by hand." 'Red'
        exit 2
    }
    Say 'Start request sent. Waiting for Video Studio (up to 90 s) ...'

    # 4. Poll
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

# 5. Browser
if (-not $NoBrowser) {
    $opera = Find-Opera
    if ($opera) {
        Say "Opening $Studio in Opera ..."
        Start-Process -FilePath $opera -ArgumentList $Studio
    } else {
        Say "Opera not found (checked LOCALAPPDATA, Program Files, Program Files (x86)). Open $Studio yourself." 'Yellow'
    }
}

# 6. Done
Say "Video Studio is up at $Studio" 'Green'
exit 0
