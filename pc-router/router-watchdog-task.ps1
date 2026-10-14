# Capture only bounded non-secret exception metadata for scheduled recovery.
$ErrorActionPreference='Stop'
try {
 & 'C:\ProgramData\OracovaNativeRemote\router-watchdog-20261014.ps1'
 exit 0
} catch {
 $receipt=@{at=[DateTimeOffset]::UtcNow.ToString('o');type=$_.Exception.GetType().FullName;line=$_.InvocationInfo.ScriptLineNumber;script=[IO.Path]::GetFileName($_.InvocationInfo.ScriptName)}
 [IO.File]::WriteAllText('C:\ProgramData\KhadangRouter\state\watchdog-task-error.json',($receipt|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
 exit 1
}
