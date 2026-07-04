' Double-click this to run Cookie Guard silently in the background (no window).
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
folder  = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = folder
' 0 = hidden window, False = don't wait
sh.Run "pythonw """ & folder & "\cookie_guard.py"" --browser brave", 0, False
