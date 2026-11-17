# Runs Llano Lights' setup.ps1 under PowerShell 7 on Linux with Windows' shortcut COM object, process list
# and registry stood in, against a pretend user profile. Proves setup.ps1's own logic, not Windows itself.
param([string]$Setup, [string]$Work)
$ErrorActionPreference = "Stop"
$fails = 0
function Check($ok, $what) { if ($ok) { Write-Host "PASS $what" } else { Write-Host "FAIL $what"; $script:fails++ } }

class FakeLnk {
    [string]$Path; [string]$TargetPath; [string]$Arguments; [string]$WorkingDirectory; [string]$IconLocation; [string]$Description
    [void] Save() {
        $this | Select-Object TargetPath, Arguments, WorkingDirectory, IconLocation, Description | ConvertTo-Json |
            Set-Content -LiteralPath $this.Path
    }
}
class FakeShell {
    [object] CreateShortcut([string]$p) {
        $l = [FakeLnk]::new(); $l.Path = $p
        if (Test-Path -LiteralPath $p) {
            $j = Get-Content -Raw -LiteralPath $p | ConvertFrom-Json
            foreach ($n in "TargetPath", "Arguments", "WorkingDirectory", "IconLocation", "Description") { $l.$n = $j.$n }
        }
        return $l
    }
}
function New-Object {
    param([Parameter(Position = 0)][string]$TypeName, [string]$ComObject, [Parameter(Position = 1)][object[]]$ArgumentList)
    if ($ComObject -eq "WScript.Shell") { return [FakeShell]::new() }
    if ($ArgumentList) { return Microsoft.PowerShell.Utility\New-Object -TypeName $TypeName -ArgumentList $ArgumentList }
    return Microsoft.PowerShell.Utility\New-Object -TypeName $TypeName
}
$global:Procs = @(); $global:Stopped = @()
function Get-CimInstance { [CmdletBinding()] param([Parameter(Position = 0)][string]$ClassName) return $global:Procs }
function Stop-Process { [CmdletBinding()] param([int]$Id, [switch]$Force) $global:Stopped += $Id }
function Unblock-File { [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$InputObject) process {} }
$global:Reg = @{}
function New-Item {
    param([string]$Path, [string]$ItemType, [switch]$Force)
    if ($Path -like "HKCU:*") { if (-not $global:Reg[$Path]) { $global:Reg[$Path] = @{} }; return }
    Microsoft.PowerShell.Management\New-Item -Path $Path -ItemType $ItemType -Force:$Force
}
function Set-ItemProperty { param([string]$LiteralPath, [string]$Name, $Value, [string]$Type) $global:Reg[$LiteralPath][$Name] = $Value }
function Get-ItemProperty {
    [CmdletBinding()] param([string]$LiteralPath, [string]$Name)
    $ErrorAction = $PSBoundParameters["ErrorAction"]
    $k = $global:Reg[$LiteralPath]
    if (-not $k -or ($Name -and -not $k.ContainsKey($Name))) {
        if ($ErrorAction -eq "Stop") { throw "no such key" }; return $null
    }
    return [pscustomobject]$k
}

function NewCopy($dir, $version) {
    foreach ($d in "runtime", "app\tools\gigbar_lights", "Mixxx mapping") { Microsoft.PowerShell.Management\New-Item -ItemType Directory -Force -Path (Join-Path $dir $d) | Out-Null }
    foreach ($f in "runtime\pythonw.exe", "app\gigbar_app.py", "llano-lights.ico", "Llano Lights.bat", "Setup.bat",
                   "Mixxx mapping\Llano-Light-Link.js", "Mixxx mapping\Llano-Light-Link.midi.xml") {
        Set-Content -LiteralPath (Join-Path $dir $f) -Value "x"
    }
    Set-Content -LiteralPath (Join-Path $dir "app\tools\gigbar_lights\version.py") -Value "VERSION = `"$version`""
}
function CopySetup($dir) {  # the build writes llano-lights.install; a source checkout has none
    foreach ($f in "setup.ps1", "uninstall.ps1") { Copy-Item (Join-Path $Setup $f) $dir }
    Set-Content -LiteralPath (Join-Path $dir "llano-lights.install") -Value "app`nruntime`nSetup.bat`nsetup.ps1`nuninstall.ps1`nllano-lights.install"
}
function Lnk($path, $target, $args_ = "") {
    $l = [FakeShell]::new().CreateShortcut($path); $l.TargetPath = $target; $l.Arguments = $args_; $l.Save()
}
function Target($path) { return [FakeShell]::new().CreateShortcut($path).TargetPath }

function Scenario($name) {
    $global:base = Join-Path $Work $name
    if (Test-Path $global:base) { Microsoft.PowerShell.Management\Remove-Item -Recurse -Force $global:base }
    $h = Join-Path $global:base "home"
    foreach ($d in "Desktop", "Start Menu\Programs", "Taskbar", "Downloads", "Documents", "Public Desktop", "Common Programs", "LocalAppData", "Temp") {
        Microsoft.PowerShell.Management\New-Item -ItemType Directory -Force -Path (Join-Path $h $d) | Out-Null
    }
    $env:LOCALAPPDATA = Join-Path $h "LocalAppData"; $env:TEMP = Join-Path $h "Temp"; $env:SystemRoot = (Join-Path $h "Windows")
    $env:OneDrive = ""
    $global:Procs = @(); $global:Stopped = @(); $global:Reg = @{}
    $new = Join-Path $h "Documents\Llano-Lights"
    NewCopy $new "1.2.2"
    CopySetup $new
    return $h, $new
}
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LlanoLights"

# --- 1: his PC. 1.1.0 unzipped in Downloads and still running, shortcuts to it, 1.2.2 unzipped in Documents.
$h, $new = Scenario "his-pc"
$old = Join-Path $h "Downloads\Llano-Lights-1.1.0\Llano-Lights"
NewCopy $old "1.1.0"
Set-Content -LiteralPath (Join-Path $old "my notes.txt") -Value "his own file"
Lnk (Join-Path $h "Desktop\Llano Lights.lnk") (Join-Path $old "runtime\pythonw.exe") "`"$old\app\gigbar_app.py`""
Lnk (Join-Path $h "Desktop\Llano Lights.bat - Shortcut.lnk") (Join-Path $old "Llano Lights.bat")
Lnk (Join-Path $h "Taskbar\Llano Lights.lnk") "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" "--app=http://127.0.0.1:8765/ --user-data-dir=C:\Users\l\AppData\Local\Llano Lights\window"
Lnk (Join-Path $h "Start Menu\Programs\GigBAR Lights.lnk") (Join-Path $old "runtime\pythonw.exe")
Lnk (Join-Path $h "Desktop\Notepad.lnk") "C:\Windows\notepad.exe"
$global:Procs = @(
    [pscustomobject]@{ ProcessId = 101; ExecutablePath = (Join-Path $old "runtime\pythonw.exe"); CommandLine = "pythonw gigbar_app.py" },
    [pscustomobject]@{ ProcessId = 102; ExecutablePath = "C:\Edge\msedge.exe"; CommandLine = "msedge --app=http://127.0.0.1:8765/ --user-data-dir=C:\Users\l\AppData\Local\Llano Lights\window" },
    [pscustomobject]@{ ProcessId = 103; ExecutablePath = "C:\Windows\explorer.exe"; CommandLine = "explorer" })
& (Join-Path $new "setup.ps1") -Quiet -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
$py = Join-Path $new "runtime\pythonw.exe"
$log = Get-Content -Raw (Join-Path $env:LOCALAPPDATA "Llano Lights\setup.log")
Check ($rc -eq 0) "his-pc: setup exits 0 (got $rc)"
Check (($global:Stopped | Sort-Object) -join "," -eq "101,102") "his-pc: closed the running 1.1.0 and its Edge window, nothing else ($($global:Stopped -join ','))"
Check ((Target (Join-Path $h "Desktop\Llano Lights.lnk")) -eq $py) "his-pc: desktop shortcut now opens 1.2.2"
Check ((Target (Join-Path $h "Desktop\Llano Lights.bat - Shortcut.lnk")) -eq $py) "his-pc: his hand-made .bat shortcut redirected"
Check ((Target (Join-Path $h "Taskbar\Llano Lights.lnk")) -eq $py) "his-pc: taskbar pin of the old window redirected"
Check ((Target (Join-Path $h "Start Menu\Programs\Llano Lights.lnk")) -eq $py) "his-pc: Start menu shortcut made"
Check (-not (Test-Path -LiteralPath (Join-Path $h "Start Menu\Programs\GigBAR Lights.lnk"))) "his-pc: GigBAR shortcut removed"
Check ((Target (Join-Path $h "Desktop\Notepad.lnk")) -eq "C:\Windows\notepad.exe") "his-pc: unrelated shortcut untouched"
Check ($global:Reg[$key].DisplayVersion -eq "1.2.2" -and $global:Reg[$key].InstallLocation -eq $new) "his-pc: Apps entry says 1.2.2 in the new folder"
Check ($global:Reg[$key].UninstallString -like "*uninstall.ps1*") "his-pc: Apps entry has Uninstall"
Check (Test-Path (Join-Path $env:LOCALAPPDATA "Mixxx\controllers\Llano-Light-Link.js")) "his-pc: Mixxx mapping copied"
Check ($log -match "Older copies of Llano Lights found" -and $log.Contains($old) -and $log -match "1\.1\.0") "his-pc: old 1.1.0 copy found and named"
Check ((Test-Path $old) -and $log -match "Kept the older copies") "his-pc: -Quiet keeps the old copy"
Check ($log -match "INSTALLED\. Llano Lights 1\.2\.2 is installed") "his-pc: says INSTALLED with the version"

# --- 2: same, answering Yes to deleting old copies: only Llano's files go, his own file stays.
$h, $new = Scenario "remove-old"
$old = Join-Path $h "Downloads\Llano-Lights"
NewCopy $old "1.1.0"
Set-Content -LiteralPath (Join-Path $old "my notes.txt") -Value "his own file"
$old2 = Join-Path $h "Desktop\Llano-Lights-1.0.4\Llano-Lights"
NewCopy $old2 "1.0.4"
& (Join-Path $new "setup.ps1") -Quiet -RemoveOld -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
Check ($rc -eq 0) "remove-old: exits 0"
Check (-not (Test-Path (Join-Path $old "runtime")) -and -not (Test-Path (Join-Path $old "app"))) "remove-old: 1.1.0 app files deleted"
Check (Test-Path (Join-Path $old "my notes.txt")) "remove-old: his own file in that folder kept"
Check (-not (Test-Path $old2)) "remove-old: a copy with only Llano files is gone, folder too"
Check ((Test-Path (Join-Path $new "runtime\pythonw.exe"))) "remove-old: the new copy is untouched"

# --- 3: a shortcut can't be saved (Start menu folder is a file): loud failure naming the step.
$h, $new = Scenario "fail-shortcut"
Microsoft.PowerShell.Management\Remove-Item -Recurse -Force (Join-Path $h "Start Menu\Programs")
Set-Content -LiteralPath (Join-Path $h "Start Menu\Programs") -Value "not a folder"
& (Join-Path $new "setup.ps1") -Quiet -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
$log = Get-Content -Raw (Join-Path $env:LOCALAPPDATA "Llano Lights\setup.log")
Check ($rc -eq 1) "fail-shortcut: exits 1 (got $rc)"
Check ($log -match "SETUP FAILED while making the Start menu and desktop shortcuts") "fail-shortcut: names the step"
Check (-not ($log -match "INSTALLED\.")) "fail-shortcut: never says INSTALLED"

# --- 4: run from a folder missing its runtime (opened inside the zip): refuses with how to fix it.
$h, $new = Scenario "incomplete"
Microsoft.PowerShell.Management\Remove-Item -Recurse -Force (Join-Path $new "runtime")
& (Join-Path $new "setup.ps1") -Quiet -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
$log = Get-Content -Raw (Join-Path $env:LOCALAPPDATA "Llano Lights\setup.log")
Check ($rc -eq 1 -and $log -match "Extract All") "incomplete: exits 1 and says Extract All"

# --- 5: running from the temp folder (Explorer opened it inside the zip).
$h, $new = Scenario "from-temp"
$tmpCopy = Join-Path $env:TEMP "Temp1_Llano-Lights-1.2.2.zip\Llano-Lights"
NewCopy $tmpCopy "1.2.2"
CopySetup $tmpCopy
& (Join-Path $tmpCopy "setup.ps1") -Quiet -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
$log = Get-Content -Raw (Join-Path $env:LOCALAPPDATA "Llano Lights\setup.log")
Check ($rc -eq 1 -and $log -match "temporary folder") "from-temp: exits 1 and says it ran from inside the zip"

# --- 6: run twice: the second run changes nothing it doesn't need to and still passes.
$h, $new = Scenario "rerun"
& (Join-Path $new "setup.ps1") -Quiet -TestHome $h *> $null
& (Join-Path $new "setup.ps1") -Quiet -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
$log = Get-Content -Raw (Join-Path $env:LOCALAPPDATA "Llano Lights\setup.log")
Check ($rc -eq 0 -and -not ($log -match "Pointed the shortcut")) "rerun: exits 0, no needless rewrites"

# --- 7: the Apps entry spells THIS folder another way (a link, like a mapped drive or 8.3 name): never deleted.
$h, $new = Scenario "self-alias"
$alias = Join-Path $h "alias-to-new"
Microsoft.PowerShell.Management\New-Item -ItemType SymbolicLink -Path $alias -Target $new | Out-Null
$global:Reg[$key] = @{ InstallLocation = $alias; DisplayVersion = "1.2.1"; InstallDate = "20261101" }
& (Join-Path $new "setup.ps1") -Quiet -RemoveOld -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
Check ($rc -eq 0 -and (Test-Path (Join-Path $new "runtime\pythonw.exe")) -and (Test-Path (Join-Path $new "app\gigbar_app.py"))) "self-alias: setup never deletes its own copy (rc $rc)"
Check ($global:Reg[$key].InstallDate -eq "20261101") "self-alias: the first install date is kept"
Check (-not (Get-ChildItem -Force $new | Where-Object { $_.Name -like ".llano-lights-setup-*" })) "self-alias: the marker file is cleaned up"

# --- 8: a zip extracted straight onto the Desktop: the Desktop is never treated as an old copy.
$h, $new = Scenario "flat-desktop"
NewCopy (Join-Path $h "Desktop") "1.1.0"
Set-Content -LiteralPath (Join-Path $h "Desktop\README.txt") -Value "his readme"
& (Join-Path $new "setup.ps1") -Quiet -RemoveOld -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
Check ($rc -eq 0 -and (Test-Path (Join-Path $h "Desktop\README.txt")) -and (Test-Path (Join-Path $h "Desktop\app"))) "flat-desktop: nothing on the Desktop deleted"

# --- 9: an old shortcut on the shared desktop it can't change (needs admin): noted, install still finishes.
$h, $new = Scenario "shared-readonly"
$old = Join-Path $h "Downloads\Llano-Lights"
NewCopy $old "1.1.0"
$pub = Join-Path $h "Public Desktop\Llano Lights.lnk"
Lnk $pub (Join-Path $old "runtime\pythonw.exe")
chmod a-w (Join-Path $h "Public Desktop") $pub
& (Join-Path $new "setup.ps1") -Quiet -TestHome $h *> (Join-Path $global:base "out.txt")
$rc = $LASTEXITCODE
chmod u+w (Join-Path $h "Public Desktop") $pub
$log = Get-Content -Raw (Join-Path $env:LOCALAPPDATA "Llano Lights\setup.log")
Check ($rc -eq 0 -and $log -match "Couldn't change the shortcut" -and $log -match "INSTALLED\.") "shared-readonly: noted, still INSTALLED (rc $rc)"
Check ((Target (Join-Path $h "Start Menu\Programs\Llano Lights.lnk")) -eq (Join-Path $new "runtime\pythonw.exe")) "shared-readonly: Start menu shortcut still made"

Write-Host ""
Write-Host ("{0} failure(s)" -f $fails)
exit $fails
