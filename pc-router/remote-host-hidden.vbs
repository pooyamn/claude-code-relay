Option Explicit
' GUI-subsystem parent: no console is created before PowerShell reads its flags.
' Wait and propagate the exit code so Scheduler retries/IgnoreNew still work.
Dim provider, command, shell, result
If WScript.Arguments.Count <> 1 Then WScript.Quit 64
provider = WScript.Arguments(0)
If provider = "--self-test" Then
    command = """C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -Command ""exit 37"""
Else
    If provider <> "Claude" And provider <> "Codex" Then WScript.Quit 64
    command = """C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File ""C:\ProgramData\OracovaNativeRemote\remote-host.ps1"" -Provider " & provider
End If
Set shell = CreateObject("WScript.Shell")
result = shell.Run(command, 0, True)
WScript.Quit result
