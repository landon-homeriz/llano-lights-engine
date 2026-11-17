# Llano Lights setup. Makes THIS folder the one Llano Lights: closes any copy that is open, points every
# older Llano Lights shortcut (desktop, Start menu, taskbar pins) at this one, makes the Start menu and
# desktop shortcuts, lists itself in Settings > Apps with Uninstall, copies the Mixxx mapping, offers to
# delete older unzipped copies, and ends by saying plainly whether it worked. Every step is checked and
# written to %LOCALAPPDATA%\Llano Lights\setup.log.
#   -Quiet  no questions or boxes (tests): keeps older copies, doesn't open the app
#   -RemoveOld  with -Quiet: answer Yes to deleting older copies (tests)
#   -TestHome  pretend this folder is the user profile (tests): where shortcuts and old copies are looked for
param([switch]$Quiet, [switch]$RemoveOld, [string]$TestHome = "")
$ErrorActionPreference = "Stop"
$root = (Split-Path -Parent $MyInvocation.MyCommand.Path).TrimEnd("\")
$python = Join-Path $root "runtime\pythonw.exe"  # no console window behind the app
$app = Join-Path $root "app"
$icon = Join-Path $root "llano-lights.ico"
$manifest = "llano-lights.install"
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LlanoLights"
$ports = 8765..8784
$dataDir = Join-Path $env:LOCALAPPDATA "Llano Lights"
$log = Join-Path $dataDir "setup.log"
$script:step = "starting"
$done = New-Object System.Collections.Generic.List[string]

function Say($text) {
    Write-Host $text
    try { Add-Content -LiteralPath $log -Value ("[" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "] " + $text) } catch {}
}
function Box($text, $buttons, $icon) {
    if ($Quiet) { return "OK" }
    Add-Type -AssemblyName System.Windows.Forms
    return [string][System.Windows.Forms.MessageBox]::Show($text, "Llano Lights setup", $buttons, $icon)
}
function Folder($name) {
    if ($TestHome) {
        $sub = @{ Desktop = "Desktop"; Programs = "Start Menu\Programs"; CommonDesktopDirectory = "Public Desktop";
                  CommonPrograms = "Common Programs"; Taskbar = "Taskbar"; Downloads = "Downloads";
                  MyDocuments = "Documents" }
        return (Join-Path $TestHome $sub[$name])
    }
    switch ($name) {
        "Taskbar" { return (Join-Path $env:APPDATA "Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar") }
        "Downloads" { return (Join-Path $env:USERPROFILE "Downloads") }
        default { return [Environment]::GetFolderPath($name) }
    }
}
function VersionOf($dir) {
    $v = Join-Path $dir "app\tools\gigbar_lights\version.py"
    if (Test-Path -LiteralPath $v) {
        $m = Select-String -LiteralPath $v -Pattern '^VERSION = "([^"]+)"' | Select-Object -First 1
        if ($m) { return $m.Matches[0].Groups[1].Value }
    }
    return "an older version"
}
function IsCopy($dir) {
    return $dir -and (Test-Path -LiteralPath (Join-Path $dir "runtime\pythonw.exe")) -and
        (Test-Path -LiteralPath (Join-Path $dir "app\gigbar_app.py"))
}
function Same($a, $b) { return [string]::Equals(([string]$a).TrimEnd("\"), ([string]$b).TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase) }
# The same folder can be spelled two ways (a mapped drive, a short 8.3 name, a junction), so "is this the copy
# Setup runs from" is answered by a marker file Setup drops in its own folder, not by comparing paths.
$marker = ".llano-lights-setup-" + [guid]::NewGuid().ToString("N")
function Mine($dir) { return $dir -and ((Same $dir $root) -or (Test-Path -LiteralPath (Join-Path $dir $marker))) }
function Finish($code) {
    Remove-Item -LiteralPath (Join-Path $root $marker) -Force -ErrorAction SilentlyContinue
    exit $code
}
# Never treat a user or Windows folder (or a drive root) as an old copy: a zip extracted straight onto the
# Desktop makes the Desktop look like one.
function Guarded($dir) {
    $d = ([string]$dir).TrimEnd("\", "/")
    if ($d.Length -le 3 -or [IO.Path]::GetPathRoot("$d\").TrimEnd("\", "/") -eq $d) { return $true }
    $special = @("Desktop", "Downloads", "MyDocuments", "Programs", "CommonDesktopDirectory", "CommonPrograms") |
        ForEach-Object { Folder $_ }
    $special += @([Environment]::GetFolderPath("UserProfile"), [Environment]::GetFolderPath("LocalApplicationData"),
                  [Environment]::GetFolderPath("ApplicationData"), $env:USERPROFILE, $env:OneDrive, $env:TEMP, $TestHome)
    return [bool]($special | Where-Object { $_ -and (Same $_ $d) })
}
function AddOld($c) {
    if ((IsCopy $c) -and -not (Mine $c) -and -not (Guarded $c) -and -not ($c -match '\.(new|old)$')) { $old[$c.ToLower()] = $c }
}
# Delete, falling back to .NET where Windows PowerShell 5.1's Remove-Item refuses (OneDrive cloud files).
function RemoveHard($path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $path) {
        try {
            if (Test-Path -LiteralPath $path -PathType Container) { [IO.Directory]::Delete($path, $true) }
            else { [IO.File]::Delete($path) }
        } catch { $script:lastError = $_.Exception.Message }
    }
}
# The Llano Lights folder a shortcut opens, or "" when it isn't one of ours. Covers the app shortcut
# (runtime\pythonw.exe), one made to "Llano Lights.bat" or Setup.bat, and a taskbar pin of the old app
# window (Edge started with Llano Lights' own window profile).
function ShortcutCopy($lnk) {
    $t = [string]$lnk.TargetPath; $a = [string]$lnk.Arguments
    if ($t -match '^(.*)[\\/]runtime[\\/]pythonw?\.exe$' -and (IsCopy $Matches[1])) { return $Matches[1] }
    if ($t -match '^(.*)[\\/](Llano Lights|GigBAR Lights|Setup)\.bat$' -and (IsCopy $Matches[1])) { return $Matches[1] }
    if ($t -match 'msedge\.exe$' -and $a -match 'Llano Lights[\\/](edge-)?window') { return "(window)" }
    return ""
}
function MakeShortcut($path) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $python
    $lnk.Arguments = "`"$app\gigbar_app.py`""
    $lnk.WorkingDirectory = $app
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = "Llano Lights: Mixxx light show"
    $lnk.Save()
    if (-not (Test-Path -LiteralPath $path)) { throw "Windows didn't save the shortcut $path" }
    if (-not (Same ([string]$shell.CreateShortcut($path).TargetPath) $python)) { throw "The shortcut $path doesn't point at $python" }
}

try {
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $version = VersionOf $root
    Say "Llano Lights $version setup, in $root"

    $script:step = "checking the folder"
    if (-not (IsCopy $root) -or -not (Test-Path -LiteralPath (Join-Path $root "uninstall.ps1"))) {
        throw "This folder is missing parts of Llano Lights. Right-click the zip, choose Extract All, open the new folder and run Setup.bat there."
    }
    Set-Content -LiteralPath (Join-Path $root $marker) -Value "Llano Lights setup is running from this folder"
    # Long names: TEMP is often a short 8.3 path (C:\Users\JOHNSM~1\...), so compare the expanded forms.
    $tmp = if ($env:TEMP -and (Test-Path -LiteralPath $env:TEMP)) { (Get-Item -LiteralPath $env:TEMP).FullName.TrimEnd("\", "/") } else { "" }
    $root = (Get-Item -LiteralPath $root).FullName.TrimEnd("\", "/")
    if ($tmp -and $root.Length -gt $tmp.Length -and $root.StartsWith($tmp, [StringComparison]::OrdinalIgnoreCase) -and
            "\/".Contains([string]$root[$tmp.Length])) {
        throw "Setup is running from Windows' temporary folder, which means it was opened from inside the zip. Right-click the zip, choose Extract All, then run Setup.bat from the new folder. Put that folder somewhere it can stay, like Documents."
    }

    $script:step = "unblocking the files"
    # Clear the "downloaded from the internet" flag so Windows doesn't block or warn on every start.
    Get-ChildItem -LiteralPath $root -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

    $script:step = "closing Llano Lights copies that are open"
    # An open copy answers every new launch with its own window, so close them all first (this one too:
    # it opens again at the end). Our app runs from <copy>\runtime; its window is Edge with our profile.
    $closed = 0
    $openCopies = New-Object System.Collections.Generic.List[string]
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessId -ne $PID } | ForEach-Object {
        $exe = [string]$_.ExecutablePath; $cmd = [string]$_.CommandLine
        $ours = $false
        if ($exe -match '^(.*)[\\/]runtime[\\/]pythonw?\.exe$' -and (IsCopy $Matches[1])) {
            $ours = $true
            $openCopies.Add($Matches[1])
        } elseif ($cmd -match 'Llano Lights[\\/](edge-)?window' -or $cmd -match 'llano-lights-swap-') { $ours = $true }
        if ($ours) { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $closed++ }
    }
    if ($closed) { Start-Sleep -Seconds 1; Say "Closed $closed Llano Lights program(s) that were open." }

    $script:step = "finding older copies and their shortcuts"
    $shell = New-Object -ComObject WScript.Shell
    $places = @("Desktop", "CommonDesktopDirectory", "Programs", "CommonPrograms", "Taskbar") |
        ForEach-Object { Folder $_ } | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $old = @{}
    foreach ($c in $openCopies) { AddOld $c }
    $links = New-Object System.Collections.Generic.List[object]
    foreach ($place in $places) {
        Get-ChildItem -LiteralPath $place -Recurse -Filter "*.lnk" -File -ErrorAction SilentlyContinue | ForEach-Object {
            try { $l = $shell.CreateShortcut($_.FullName) } catch { return }
            $copy = ShortcutCopy $l
            if ($copy) {
                $links.Add($_.FullName)
                if ($copy -ne "(window)") { AddOld $copy }
            }
        }
    }
    try {  # the folder the Apps list knew, if it was another one
        $was = (Get-ItemProperty -LiteralPath $key -ErrorAction Stop).InstallLocation
        AddOld $was
    } catch {}
    # unzipped copies where people unzip things (three folders deep)
    foreach ($base in @((Folder "Downloads"), (Folder "Desktop"), (Folder "MyDocuments"), $env:OneDrive)) {
        if (-not $base -or -not (Test-Path -LiteralPath $base)) { continue }
        Get-ChildItem -LiteralPath $base -Directory -Recurse -Depth 3 -Filter "runtime" -ErrorAction SilentlyContinue | ForEach-Object {
            AddOld $_.Parent.FullName
        }
    }

    $script:step = "pointing older shortcuts at this copy"
    $redirected = 0
    foreach ($path in $links) {
        # One shortcut Windows won't let us change (the shared desktop needs admin) is noted, never fatal.
        try {
            $name = [IO.Path]::GetFileNameWithoutExtension($path)
            if ($name -eq "GigBAR Lights") { Remove-Item -LiteralPath $path -Force; continue }  # the old name
            $l = $shell.CreateShortcut($path)
            if ((Same ([string]$l.TargetPath) $python) -and ($l.Arguments -eq "`"$app\gigbar_app.py`"")) { continue }
            MakeShortcut $path
            $redirected++
            Say "Pointed the shortcut $path at this copy."
        } catch {
            Say "Couldn't change the shortcut $path ($($_.Exception.Message)). It may still open an older copy; delete it by hand."
        }
    }
    if ($redirected) { $done.Add("Pointed $redirected older shortcut(s) at $version") }

    $script:step = "making the Start menu and desktop shortcuts"
    $startMenu = Join-Path (Folder "Programs") "Llano Lights.lnk"
    $desktop = Join-Path (Folder "Desktop") "Llano Lights.lnk"
    foreach ($path in @($startMenu, $desktop)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null
        MakeShortcut $path
    }
    Say "Added 'Llano Lights' to the Start menu ($startMenu) and the desktop ($desktop)."
    $done.Add("Start menu and desktop shortcuts")

    $script:step = "listing Llano Lights in Settings > Apps"
    # The same entry the app writes each time it starts (windows_apps.py), written here too so Uninstall
    # is there even before the first start. Per user, so no admin prompt.
    $kb = [int]((Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1024)
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $key)) { New-Item -Path $key -Force | Out-Null }  # -Force on an existing key empties it
    $vals = [ordered]@{ DisplayName = "Llano Lights"; DisplayVersion = $version; Publisher = "Llano";
        DisplayIcon = $icon; InstallLocation = $root;
        UninstallString = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\uninstall.ps1`"" }
    foreach ($n in $vals.Keys) { Set-ItemProperty -LiteralPath $key -Name $n -Value $vals[$n] -Type String }
    if (-not (Get-ItemProperty -LiteralPath $key -Name InstallDate -ErrorAction SilentlyContinue)) {
        Set-ItemProperty -LiteralPath $key -Name InstallDate -Value (Get-Date -Format "yyyyMMdd") -Type String
    }
    foreach ($n in @("EstimatedSize", "NoModify", "NoRepair")) {
        $v = if ($n -eq "EstimatedSize") { $kb } else { 1 }
        Set-ItemProperty -LiteralPath $key -Name $n -Value $v -Type DWord
    }
    $check = Get-ItemProperty -LiteralPath $key
    if ($check.DisplayVersion -ne $version -or -not (Same $check.InstallLocation $root)) { throw "Windows didn't keep the Apps list entry" }
    Say "Listed Llano Lights $version in Settings > Apps, with Uninstall."
    $done.Add("Listed in Settings > Apps, with Uninstall")

    $script:step = "copying the Mixxx mapping"
    $controllers = Join-Path $env:LOCALAPPDATA "Mixxx\controllers"
    New-Item -ItemType Directory -Force -Path $controllers | Out-Null
    Copy-Item -Force -LiteralPath (Join-Path $root "Mixxx mapping\Llano-Light-Link.js") -Destination $controllers
    Copy-Item -Force -LiteralPath (Join-Path $root "Mixxx mapping\Llano-Light-Link.midi.xml") -Destination $controllers
    Say "Copied the Mixxx mapping files to $controllers"
    $done.Add("Mixxx mapping files")

    $script:step = "removing older copies"
    if ($old.Count) {
        $list = ($old.Values | ForEach-Object { "  " + $_ + "  (" + (VersionOf $_) + ")" }) -join "`n"
        Say "Older copies of Llano Lights found:`n$list"
        $ans = if ($Quiet) { if ($RemoveOld) { "Yes" } else { "No" } } else {
            Box ("Found older copies of Llano Lights:`n`n$list`n`nDelete them so only $version is left? " +
                 "Their shortcuts already open $version. Your saved layouts are kept either way.") "YesNo" "Question" }
        if ($ans -eq "Yes") {
            # Only Llano Lights' own files (the build's list, or the names every build has used), then
            # the folder if that emptied it. Never a drive root or a folder that isn't a Llano copy.
            $names = @("runtime", "app", "Mixxx mapping", "Setup.bat", "setup.ps1", "uninstall.ps1", "Llano Lights.bat",
                       "GigBAR Lights.bat", "llano-lights.ico", "Llano Lights - How to install.pdf", "README.txt", $manifest)
            $removed = 0
            foreach ($c in $old.Values) {
                if (-not (IsCopy $c) -or (Mine $c) -or (Guarded $c)) { continue }
                $own = $names
                if (Test-Path -LiteralPath (Join-Path $c $manifest)) {
                    $own += Get-Content -LiteralPath (Join-Path $c $manifest) | ForEach-Object { $_.Trim() } |
                        Where-Object { $_ -and $_ -notmatch '[\\/:]' -and $_ -ne "." -and $_ -ne ".." }
                }
                Get-ChildItem -LiteralPath $c -Force | Where-Object { ($own -contains $_.Name) -or ($_.Name -like "*GigBAR*.pdf") } |
                    ForEach-Object { RemoveHard $_.FullName }
                if (Test-Path -LiteralPath (Join-Path $c "runtime")) {
                    $why = if ($script:lastError) { " ($script:lastError)" } else { "" }
                    Say "Couldn't fully delete $c$why; delete it by hand after a restart."
                }
                else {
                    $removed++
                    if (-not (Get-ChildItem -LiteralPath $c -Force)) { RemoveHard $c }
                    Say "Deleted the older copy in $c"
                }
            }
            if ($removed) { $done.Add("Deleted $removed older copy(ies)") }
        } else {
            Say "Kept the older copies; their shortcuts open $version now."
        }
    }

    $script:step = "finishing"
    $summary = "Llano Lights $version is installed in`n$root`n`n" + (($done | ForEach-Object { "  - " + $_ }) -join "`n")
    Say ""
    Say "INSTALLED. $summary"
    if ($Quiet) { Finish 0 }

    if ((Box ($summary + "`n`nOpen Llano Lights $version now?") "YesNo" "Information") -ne "Yes") {
        Say "Open it any time from the Start menu or the desktop."
        Finish 0
    }
    $script:step = "opening Llano Lights"
    Start-Process -FilePath $python -ArgumentList "`"$app\gigbar_app.py`"" -WorkingDirectory $app
    # Prove the window that opens is this version, from this folder.
    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline) {
        foreach ($p in $ports) {
            try {
                $req = [Net.HttpWebRequest]::Create("http://127.0.0.1:$p/api/app")
                $req.Proxy = $null; $req.Timeout = 700
                $resp = $req.GetResponse()
                $body = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd(); $resp.Close()
                $info = $body | ConvertFrom-Json
                if ($info.product -eq "llano-lights" -and $info.version -eq $version -and (Mine ([string]$info.root))) {
                    Say "Llano Lights $version is open."
                    Finish 0
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 700
    }
    $applog = Join-Path $dataDir "llano-lights.log"
    Say "Llano Lights was installed but didn't open within 40 seconds. Its log is $applog"
    Box ("Llano Lights $version is installed, but it didn't open within 40 seconds.`n`nTry the Start menu shortcut. " +
         "If it still doesn't open, send us this file:`n$applog") "OK" "Warning" | Out-Null
    Finish 3
} catch {
    $msg = $_.Exception.Message
    Say ""
    Say "SETUP FAILED while $($script:step): $msg"
    Say "Setup's record is $log"
    Box ("Setup did not finish.`n`nIt stopped while $($script:step):`n$msg`n`nSetup's record is in`n$log") "OK" "Error" | Out-Null
    Finish 1
}
