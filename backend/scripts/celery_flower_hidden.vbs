Set shell = CreateObject("WScript.Shell")
shell.Run """" & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\celery_flower.cmd" & """", 0, False
