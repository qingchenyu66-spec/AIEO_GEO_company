Set shell = CreateObject("WScript.Shell")
shell.Run """" & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\celery_worker_submit.cmd" & """", 0, False
