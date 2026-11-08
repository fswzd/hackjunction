' Hidden one-click launcher for the desktop workbench. ASCII-only on purpose:
' Windows Script Host reads .vbs as ANSI unless it has a UTF-16 BOM.
Option Explicit
Dim sh, fso, root, pyw, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
pyw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
sh.CurrentDirectory = root
cmd = """" & pyw & """ """ & root & "\desktop\launch.py"""
sh.Run cmd, 0, False
