Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' مسیر پروژه = همان پوشه‌ای که این فایل در آن است
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)

' اجرای start.bat به صورت مخفی (بدون باز شدن پنجره سیاه دائمی)
WshShell.Run "cmd /c cd /d """ & projectDir & """ && start.bat", 0, False
