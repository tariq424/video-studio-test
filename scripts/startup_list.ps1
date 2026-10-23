# READ-ONLY: list the Startup folder, resolve each shortcut, and show the hotkey lines of any AutoHotkey script it starts.
# Also the running AutoHotkey processes. Report: F:\videos_test\smoke\startup_report.txt
$out = 'F:\videos_test\smoke\startup_report.txt'
$r = New-Object System.Collections.Generic.List[string]
$sh = New-Object -ComObject WScript.Shell
function Show-Ahk($p) {
    if (-not (Test-Path -LiteralPath $p)) { $r.Add("      (file not found: $p)"); return }
    $i = 0
    foreach ($l in (Get-Content -LiteralPath $p -ErrorAction SilentlyContinue)) {
        $i++
        if ($l -match '^\s*[\^!+#<>*~$]+[\w]+\s*::' -or $l -match '(?i)\bRun\b|\.html|google') { $r.Add(("      {0,4}: {1}" -f $i, $l.Trim())) }
    }
}
$r.Add("== Running AutoHotkey processes")
Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'autohotkey' } | ForEach-Object {
    $r.Add("   $($_.ProcessId)  $($_.CommandLine)")
    if ($_.CommandLine -match '"([^"]+\.ahk)"') { Show-Ahk $Matches[1] }
}
$r.Add("")
$dir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$r.Add("== $dir")
Get-ChildItem -LiteralPath $dir -ErrorAction SilentlyContinue | ForEach-Object {
    $r.Add("-- $($_.Name)")
    $target = $_.FullName
    if ($_.Extension -eq '.lnk') { $s = $sh.CreateShortcut($_.FullName); $target = $s.TargetPath; $r.Add("   -> $($s.TargetPath) $($s.Arguments)   (shortcut key: $($s.Hotkey))") ; if ($s.Arguments -match '"?([^"]+\.ahk)') { Show-Ahk $Matches[1] } }
    if ($target -match '\.ahk$') { Show-Ahk $target }
    if ($target -match '\.ahk$') { Get-ChildItem -LiteralPath (Split-Path $target) -Filter *.ahk -ErrorAction SilentlyContinue | ForEach-Object { $r.Add("   sibling: $($_.FullName)"); Show-Ahk $_.FullName } }
}
$r | Out-File -FilePath $out -Encoding utf8
