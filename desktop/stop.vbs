' Stop only the processes started by this desktop app (ASCII-only on purpose).
Option Explicit
Dim sh, fso, root, pyw, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
pyw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
sh.CurrentDirectory = root
cmd = """" & pyw & """ """ & root & "\desktop\stop.py"""
sh.Run cmd, 0, False
