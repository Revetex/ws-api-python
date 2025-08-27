Set oShell = CreateObject("WScript.Shell")
Set oFSO = CreateObject("Scripting.FileSystemObject")
base = oFSO.GetParentFolderName(WScript.ScriptFullName)
' Prefer venv/.venv pythonw
pyw = base & "\.venv\Scripts\pythonw.exe"
If Not oFSO.FileExists(pyw) Then
  pyw = base & "\venv\Scripts\pythonw.exe"
End If
If Not oFSO.FileExists(pyw) Then
  ' Last resort: try just `pythonw` in PATH
  pyw = "pythonw"
End If
cmd = Chr(34) & pyw & Chr(34) & " " & Chr(34) & base & "\gui.py" & Chr(34)
oShell.CurrentDirectory = base
' 0 = hidden window
rc = oShell.Run(cmd, 0, False)
