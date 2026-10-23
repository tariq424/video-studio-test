# READ-ONLY: find which AutoHotkey script (or .lnk shortcut key) binds Ctrl+Alt+W. Changes nothing.
# Report: F:\videos_test\smoke\ahk_report.txt
$out = 'F:\videos_test\smoke\ahk_report.txt'
$r = New-Object System.Collections.Generic.List[string]
$prof = $env:USERPROFILE
$r.Add("== Running AutoHotkey processes")
Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'autohotkey' } | ForEach-Object { $r.Add("$($_.ProcessId)  $($_.ExecutablePath)  |  $($_.CommandLine)") }
$r.Add("")
$r.Add("== .ahk files under $prof and F:\ (top levels)")
$ahk = @()
$ahk += Get-ChildItem -Path $prof -Recurse -Filter *.ahk -ErrorAction SilentlyContinue -Force | Where-Object { $_.FullName -notmatch '\\AppData\\Local\\(Packages|Temp|Microsoft\\Edge|Google\\Chrome)' }
$ahk += Get-ChildItem -Path 'F:\' -Recurse -Depth 3 -Filter *.ahk -ErrorAction SilentlyContinue
foreach ($f in $ahk) {
    $r.Add("-- $($f.FullName)  ($($f.LastWriteTime))")
    $lines = Get-Content -LiteralPath $f.FullName -ErrorAction SilentlyContinue
    $i = 0
    foreach ($l in $lines) {
        $i++
        if ($l -match '^\s*[\^!+#<>*~$]+\w+\s*::' -or $l -match '(?i)google all apps|waffle|\.html|Run\s') { $r.Add(("   {0,4}: {1}" -f $i, $l.Trim())) }
    }
}
$r.Add("")
$r.Add("== Startup folder")
Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup" -ErrorAction SilentlyContinue | ForEach-Object { $r.Add("   $($_.Name)") }
$r.Add("")
$r.Add("== .lnk shortcuts with a shortcut key (Desktop, Start Menu, Startup)")
$sh = New-Object -ComObject WScript.Shell
$dirs = @("$prof\Desktop", "$env:APPDATA\Microsoft\Windows\Start Menu", "$env:ProgramData\Microsoft\Windows\Start Menu", "$env:PUBLIC\Desktop")
foreach ($d in $dirs) {
    Get-ChildItem -Path $d -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        try { $s = $sh.CreateShortcut($_.FullName); if ($s.Hotkey) { $r.Add("   $($s.Hotkey)  $($_.FullName)  ->  $($s.TargetPath) $($s.Arguments)") } } catch {}
    }
}
$r.Add("")
$r.Add("== Files named like google*apps* / *waffle* (html) under $prof and F:\code")
Get-ChildItem -Path $prof, 'F:\code' -Recurse -Depth 4 -Include *waffle*, *google*app* -ErrorAction SilentlyContinue | Where-Object { $_.Extension -match 'html?|ahk|lnk' } | ForEach-Object { $r.Add("   $($_.FullName)") }
$r | Out-File -FilePath $out -Encoding utf8
