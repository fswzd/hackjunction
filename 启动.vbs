' Desktop entry point for the workbench. ASCII-only body: WSH reads .vbs as ANSI,
' so the Chinese folder name is assembled from code points instead of literals.
Option Explicit
Dim sh, fso, folder, root, pyw, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = ChrW(&H4F17) & ChrW(&H5E55) & "AI" & ChrW(&H5DE5) & ChrW(&H4F5C) & ChrW(&H53F0)
' Self-locating: the app root is this script's own folder (no fixed user path).
root = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
sh.CurrentDirectory = root
cmd = """" & pyw & """ """ & root & "\desktop\launch.py"""
sh.Run cmd, 0, False
