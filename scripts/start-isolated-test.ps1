$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
if ($TestRoot -ine 'F:\code\video-studio-test') { throw 'This launcher only runs the isolated F:\code\video-studio-test checkout.' }
if (Get-NetTCPConnection -LocalPort 42021 -State Listen -ErrorAction SilentlyContinue) { throw 'Test port 42021 is already occupied; nothing was stopped.' }
$TestData = 'F:\videos_test'
New-Item -ItemType Directory -Force "$TestData\jobs", "$TestData\evidence" | Out-Null
$SettingsPath = Join-Path $TestRoot 'settings.json'
$Settings = @{}
if (Test-Path -LiteralPath $SettingsPath) {
    $Parsed = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
    $Parsed.PSObject.Properties | ForEach-Object { $Settings[$_.Name] = $_.Value }
}
$Settings.jobs_dir = "$TestData\jobs"
$Settings.ffmpeg_dir = ''
$Settings.short_concurrency = '2'
$Settings.long_renderer = 'remotion'
$Settings.qa_provider = 'off'
$Settings.vet_provider = 'off'
$Settings.cloud_on = $false
[IO.File]::WriteAllText($SettingsPath, ($Settings | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
$env:PORT = '42021'
$env:VS_RELOAD = '0'
$Process = Start-Process -FilePath "$TestRoot\app\env\Scripts\python.exe" -ArgumentList '-u', 'server.py' -WorkingDirectory "$TestRoot\app" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$TestData\evidence\server.stdout.log" -RedirectStandardError "$TestData\evidence\server.stderr.log"
$Process.Id | Set-Content -LiteralPath "$TestData\evidence\server.pid"
Write-Output "Test server started: PID $($Process.Id), port 42021, jobs $TestData\jobs"
