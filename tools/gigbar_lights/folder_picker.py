"""Browse for a folder with Windows' own folder picker (1.20.0, Llano BL #12132).

His ask, 2026-11-13, doing "Shows, A folder": pasting a path must not be the only way; a Browse
button opens the normal Windows folder picker. The Shows page runs in an Edge window, and a web
page is never told a folder's real path, so the app opens the picker itself and hands the path back.

How: Windows PowerShell (on every Windows 10 and 11) shows the Explorer-style picker
(IFileOpenDialog with "pick folders"), owned by the window he clicked in, so it opens on top of
Llano Lights. If that can't start on a laptop, the older "Browse For Folder" tree is tried, and if
that fails too the page says so and the path box still works. Proven on a real Windows desktop:
the windows-folder-picker workflow opens both pickers, presses Select Folder / OK / Cancel, and
checks the folder that comes back (tests/windows_e2e/folder_picker_e2e.py).

pick() never raises and returns (path, error): ("", "") means he pressed Cancel.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
from pathlib import Path

WAIT_S = 15 * 60          # he may browse for a while; a picker left open is given up on after this
_one = threading.Lock()   # one picker at a time: a second press is answered, never a second window

# The Explorer-style picker. The interface lists must stay in Windows' own order (a COM vtable):
# only Show, SetOptions, GetOptions, SetFolder, SetTitle and GetResult are called, the rest hold places.
MODERN = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class LlanoFolderPicker {
  [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")] class FileOpenDialog { }
  [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(); void GetParent();
    void GetDisplayName(uint sigdn, [MarshalAs(UnmanagedType.LPWStr)] out string name);
    void GetAttributes(); void Compare();
  }
  [ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileDialog {
    [PreserveSig] int Show(IntPtr owner);
    void SetFileTypes(); void SetFileTypeIndex(); void GetFileTypeIndex(); void Advise(); void Unadvise();
    void SetOptions(uint fos); void GetOptions(out uint fos);
    void SetDefaultFolder(IShellItem item); void SetFolder(IShellItem item);
    void GetFolder(); void GetCurrentSelection(); void SetFileName(); void GetFileName();
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
    void SetOkButtonLabel(); void SetFileNameLabel();
    void GetResult(out IShellItem item);
    void AddPlace(); void SetDefaultExtension(); void Close(); void SetClientGuid(); void ClearClientData(); void SetFilter();
  }
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr ctx, [In] ref Guid iid, out IShellItem item);
  public static string Pick(string title, string start) {
    IFileDialog d = (IFileDialog)new FileOpenDialog();
    uint o; d.GetOptions(out o);
    d.SetOptions(o | 0x20 | 0x40);   // pick folders, real folders on disk only
    d.SetTitle(title);
    if (!String.IsNullOrEmpty(start)) {
      try { Guid iid = new Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"); IShellItem at; SHCreateItemFromParsingName(start, IntPtr.Zero, ref iid, out at); d.SetFolder(at); } catch { }
    }
    if (d.Show(GetForegroundWindow()) != 0) return "";   // Cancel
    IShellItem it; d.GetResult(out it);
    string p; it.GetDisplayName(0x80058000, out p);        // the folder's path on disk
    return p ?? "";
  }
}
'@
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Console]::Out.Write([LlanoFolderPicker]::Pick($env:LLANO_PICK_TITLE, $env:LLANO_PICK_START))
"""

# The older tree-style picker, for a laptop where the one above can't start.
CLASSIC = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = $env:LLANO_PICK_TITLE
$d.ShowNewFolderButton = $false
if ($env:LLANO_PICK_START) { $d.SelectedPath = $env:LLANO_PICK_START }
$top = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false; Opacity = 0}
$top.Show()
$r = $d.ShowDialog($top)
$top.Close()
[Console]::OutputEncoding = [Text.Encoding]::UTF8
if ($r -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($d.SelectedPath) }
"""


def _on_windows() -> bool:
    return sys.platform == "win32"


def _powershell() -> str:
    return str(Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _run(script: str, title: str, start: str) -> tuple[int, str, str]:
    """(exit code, what it printed, its error text). The title and folder travel as environment
    values, never inside the script, so no name he has on disk can change what runs."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    env = {**os.environ, "LLANO_PICK_TITLE": title, "LLANO_PICK_START": start}
    res = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass",
                          "-EncodedCommand", encoded],
                         capture_output=True, timeout=WAIT_S, env=env,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return res.returncode, res.stdout.decode("utf-8", "replace").strip(), res.stderr.decode("utf-8", "replace").strip()


def clean(path: str) -> str:
    """A path as he pasted or picked it: Windows' "Copy as path" wraps it in quotes, a dragged
    folder can arrive as file:///C:/..., and a stray space or line break rides along."""
    p = str(path or "").strip().strip('"').strip("'").strip()
    if p.lower().startswith("file:///"):
        from urllib.parse import unquote  # noqa: PLC0415
        p = unquote(p[8:]).replace("/", "\\") if len(p) > 9 and p[9] == ":" else unquote(p[7:])
    return p


def pick(title: str = "Choose the folder your songs are in", start: str = "") -> tuple[str, str]:
    """(the folder he chose, "") | ("", "") when he cancelled | ("", why) when no picker could open."""
    if not _on_windows():
        return "", "The folder picker only works on Windows. Paste the folder's path instead."
    if not _one.acquire(blocking=False):
        return "", "The folder picker is already open. Look for it on the taskbar."
    try:
        start = clean(start)
        start = start if start and Path(start).is_dir() else ""
        last = ""
        for script in (MODERN, CLASSIC):
            try:
                code, out, err = _run(script, title[:120], start)
            except subprocess.TimeoutExpired:
                return "", "The folder picker was left open too long and was closed. Press Browse again."
            except OSError as e:
                last = str(e)
                continue
            if code == 0:
                return (out if out and Path(out).is_dir() else ""), ""
            last = err.splitlines()[0] if err else f"exit {code}"
        print(f"Folder picker could not open: {last}")
        return "", "Windows' folder picker didn't open on this laptop. Paste the folder's path in the box instead."
    finally:
        _one.release()


# One song file (Add a song from this laptop, Llano BL #12342): Windows' own Open dialog, audio files
# only, on top of the window he clicked in (a hidden topmost owner, as the classic folder picker).
FILE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = $env:LLANO_PICK_TITLE
$d.Filter = 'Songs|*.mp3;*.flac;*.wav;*.m4a;*.aac;*.ogg;*.opus;*.aiff;*.aif|All files|*.*'
$d.Multiselect = $false
$d.CheckFileExists = $true
if ($env:LLANO_PICK_START) { $d.InitialDirectory = $env:LLANO_PICK_START }
$top = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false; Opacity = 0}
$top.Show()
$r = $d.ShowDialog($top)
$top.Close()
[Console]::OutputEncoding = [Text.Encoding]::UTF8
if ($r -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($d.FileName) }
"""


def pick_file(title: str = "Choose the song", start: str = "") -> tuple[str, str]:
    """(the file he chose, "") | ("", "") when he cancelled | ("", why) when no picker could open."""
    if not _on_windows():
        return "", "The file picker only works on Windows. Paste the song file's path instead."
    if not _one.acquire(blocking=False):
        return "", "A picker is already open. Look for it on the taskbar."
    try:
        start = clean(start)
        start = start if start and Path(start).is_dir() else str(Path.home() / "Music")
        try:
            code, out, err = _run(FILE, title[:120], start)
        except subprocess.TimeoutExpired:
            return "", "The file picker was left open too long and was closed. Press Choose the song again."
        except OSError as e:
            print(f"File picker could not open: {e}")
            return "", "Windows' file picker didn't open on this laptop. Paste the song file's path instead."
        if code == 0:
            return (out if out and Path(out).is_file() else ""), ""
        print(f"File picker could not open: {err.splitlines()[0] if err else code}")
        return "", "Windows' file picker didn't open on this laptop. Paste the song file's path instead."
    finally:
        _one.release()
