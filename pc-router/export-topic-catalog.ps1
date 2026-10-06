param([Parameter(Mandatory=$true)][string]$OutputPath)
# Read-only public routing snapshot, never credentials/policy or mutation authority.
$ErrorActionPreference='Stop'
$root='C:\ProgramData\KhadangRouter'
$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
if($s.bot -ne 'TheKhadangBot' -or $s.host -ne 'DESKTOP-8SO9HDK' -or (Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2)){throw 'Fresh exact live PC router required'}
$bindings=@($s.bindings|ForEach-Object {
 $b=$_; $alias=($b.Workspace -replace '^.*[/\\]','').ToLowerInvariant() -replace '[^a-z0-9-]','-'
 if($b.Chat -eq -1003550185469 -and $b.Topic -eq 816){$alias='claude-code-relay'}
 @{Alias=$alias;Chat=$b.Chat;Topic=$b.Topic;ThreadId=$b.ThreadId;Workspace=$b.Workspace;Backend=$b.Backend;Runtime=$b.Runtime;Name=$b.Name}
})
if(@($bindings.Alias|Select-Object -Unique).Count -ne $bindings.Count -or @($bindings|Where-Object Alias -eq 'claude-code-relay').Count -ne 1){throw 'Ambiguous routing aliases'}
$bytes=[Text.Encoding]::UTF8.GetBytes((@{schema='ccrelay.pc_topics.v1';observedAt=$s.at;bindings=$bindings}|ConvertTo-Json -Depth 8 -Compress))
$f=[IO.File]::Open($OutputPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}
@{exported=$bindings.Count;credentials=$false;modelsStarted=0}|ConvertTo-Json -Compress
