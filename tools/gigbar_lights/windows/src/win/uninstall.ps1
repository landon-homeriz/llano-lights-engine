# Llano Lights uninstall. Settings > Apps runs this (the app lists itself there each time it starts).
# Removes what the build put in its folder (listed in llano-lights.install), its shortcuts, the Mixxx
# mapping files Setup copied, the updater's leftovers and the window profile + log; asks before
# deleting saved Show Designer layouts.
param([string]$Root = "")
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Windows.Forms
function Ask($text, $buttons, $icon, $default) {
    # DefaultDesktopOnly keeps the box on top of Settings, which launched us hidden.
    return [string][System.Windows.Forms.MessageBox]::Show($text, "Uninstall Llano Lights", $buttons, $icon, $default,
        [System.Windows.Forms.MessageBoxOptions]::DefaultDesktopOnly)
}
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LlanoLights"
$manifest = "llano-lights.install"

if (-not $Root) {
    # This script lives inside the folder it removes, so it carries on from a copy in the temp folder.
    $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
    $copy = Join-Path $env:TEMP ("llano-lights-uninstall-" + [guid]::NewGuid().ToString("N") + ".ps1")
    Copy-Item -Force $MyInvocation.MyCommand.Path $copy
    Start-Process -FilePath (Get-Process -Id $PID).Path -WorkingDirectory $env:TEMP -WindowStyle Hidden `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$copy`"",
                        "-Root", "`"$($Root.TrimEnd('\'))`"")
    exit 0
}
$Root = $Root.TrimEnd("\")
$mutex = New-Object System.Threading.Mutex($false, "LlanoLightsUninstall")
if (-not $mutex.WaitOne(0)) { exit 0 }  # one is already open (Uninstall clicked twice)

# Never work on a drive root or one of Windows' own folders, and only on a folder our build made.
$special = @("UserProfile", "Desktop", "MyDocuments", "Programs", "LocalApplicationData", "ApplicationData") |
    ForEach-Object { [Environment]::GetFolderPath($_).TrimEnd("\") }
$special += @($env:TEMP, $env:USERPROFILE, (Join-Path $env:USERPROFILE "Downloads")) | Where-Object { $_ } |
    ForEach-Object { $_.TrimEnd("\") }
$isRoot = ($Root.Length -le 3) -or ([IO.Path]::GetPathRoot("$Root\").TrimEnd("\") -eq $Root)
if ($isRoot -or ($special -contains $Root) -or -not (Test-Path -LiteralPath (Join-Path $Root $manifest) -PathType Leaf)) {
    $gone = Ask ("Llano Lights isn't installed in $Root any more (the folder was moved or deleted), so there is " +
                 "nothing to remove there. Take it off the Apps list?") "YesNo" "Question" "Button1"
    if ($gone -eq "Yes") { Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction SilentlyContinue }
    exit 0
}

$ok = Ask ("Remove Llano Lights from this PC?`n`nThis removes the app, its Start menu and desktop shortcuts, " +
           "its Mixxx mapping files and its update files. You'll be asked separately about your saved layouts.") "OKCancel" "Question" "Button1"
if ($ok -ne "OK") { exit 1 }

function Remove-Hard($path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $path) {  # OneDrive-backed folders can refuse Remove-Item
        try {
            if (Test-Path -LiteralPath $path -PathType Container) { [IO.Directory]::Delete($path, $true) }
            else { [IO.File]::Delete($path) }
        } catch { $script:lastError = $_.Exception.Message }
    }
}

# Close the app, its window and any update in progress (never this script).
$profileDir = Join-Path $env:LOCALAPPDATA "Llano Lights"
$prefixes = @("$Root\", "$Root.new\", "$Root.old\")
Get-CimInstance Win32_Process | Where-Object {
    $exe = $_.ExecutablePath; $cmd = $_.CommandLine
    ($_.ProcessId -ne $PID) -and (
        ($exe -and ($prefixes | Where-Object { $exe.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) })) -or
        ($cmd -and ($cmd.Contains("$profileDir\window") -or $cmd.Contains("$profileDir\edge-window") -or
                     $cmd.Contains("llano-lights-swap-"))))
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

foreach ($dir in @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))) {
    if (-not $dir) { continue }
    foreach ($name in @("Llano Lights.lnk", "GigBAR Lights.lnk")) { Remove-Hard (Join-Path $dir $name) }
}
# Setup (1.2.2 on) also points older shortcuts at this copy, wherever they were: a taskbar pin, one he
# made himself. Remove every shortcut that opens this copy, so none is left pointing at nothing.
$shell = New-Object -ComObject WScript.Shell
$pins = Join-Path $env:APPDATA "Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
foreach ($dir in @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"), $pins)) {
    if (-not $dir -or -not (Test-Path -LiteralPath $dir)) { continue }
    Get-ChildItem -LiteralPath $dir -Recurse -Filter "*.lnk" -File -ErrorAction SilentlyContinue | ForEach-Object {
        try { $t = [string]$shell.CreateShortcut($_.FullName).TargetPath } catch { return }
        if ($t.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase)) { Remove-Hard $_.FullName }
    }
}
$controllers = Join-Path $env:LOCALAPPDATA "Mixxx\controllers"
foreach ($f in @("Llano-Light-Link.js", "Llano-Light-Link.midi.xml")) { Remove-Hard (Join-Path $controllers $f) }

# The updater's leftovers: a half-unpacked or previous copy, the download folder, swap runtimes and log
# (in the temp folder, or beside the install when there was no usable temp folder).
$parent = Split-Path -Parent $Root
foreach ($p in @("$Root.new", "$Root.old", (Join-Path $parent ".llano-lights-download"))) { Remove-Hard $p }
foreach ($d in @($env:TEMP, $parent)) {
    if (-not $d) { continue }
    Get-ChildItem -LiteralPath $d -Directory -Filter "llano-lights-swap-*" -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Hard $_.FullName }
    Remove-Hard (Join-Path $d "llano-lights-update.log")
}
Remove-Hard $profileDir

$saved = Join-Path $env:USERPROFILE ".gigbar_lights"
if (Test-Path -LiteralPath $saved) {
    $n = @(Get-ChildItem -LiteralPath (Join-Path $saved "layouts") -Filter "*.json" -File -ErrorAction SilentlyContinue).Count
    $what = if ($n -eq 1) { "your saved Show Designer layout" } elseif ($n -gt 1) { "your $n saved Show Designer layouts" } else { "your Llano Lights settings" }
    $del = Ask ("Also delete ${what}?`n`nThey're in $saved, with any song sections Llano Lights found. " +
                "Choose No to keep them: installing Llano Lights again picks them back up.") "YesNo" "Warning" "Button2"
    if ($del -eq "Yes") { Remove-Hard $saved }
}

Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "HKCU:\Software\Classes\llano-lights" -Recurse -Force -ErrorAction SilentlyContinue  # the Start button link (BL #12377)
# Only what the build shipped (plain names, nothing that climbs out), then the folder if that emptied it.
$names = Get-Content -LiteralPath (Join-Path $Root $manifest) | ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and $_ -notmatch '[\\/:]' -and $_ -ne "." -and $_ -ne ".." }
for ($i = 0; $i -lt 10; $i++) {
    foreach ($name in $names) { Remove-Hard (Join-Path $Root $name) }
    if (-not ($names | Where-Object { Test-Path -LiteralPath (Join-Path $Root $_) })) { break }
    Start-Sleep -Seconds 1
}
$left = @($names | Where-Object { Test-Path -LiteralPath (Join-Path $Root $_) })
if (-not $left -and -not (Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue)) { Remove-Hard $Root }
if ($left) {
    $why = if ($script:lastError) { "`n`n($script:lastError)" } else { "" }
    Ask ("Llano Lights is uninstalled, but some of its files in $Root couldn't be removed ($($left -join ', ')). " +
         "Restart the PC and delete them.$why") "OK" "Information" "Button1" | Out-Null
} else {
    Ask "Llano Lights is removed." "OK" "Information" "Button1" | Out-Null
}
$mutex.ReleaseMutex()
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
exit 0
