param(
    [Parameter(Mandatory=$true)][int]$Topic,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f-]{36}$')][string]$ThreadId
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$root = 'C:\ProgramData\KhadangRouter'
$status = Get-Content "$root\state\status.json" -Raw | ConvertFrom-Json
$bound = @($status.bindings | Where-Object { $_.Topic -eq $Topic -and $_.ThreadId -eq $ThreadId })
if ($status.host -ne $env:COMPUTERNAME -or -not $status.pcOnly -or $status.bot -ne 'TheKhadangBot' -or
    $bound.Count -ne 1 -or $bound[0].Chat -ne -1004320138859 -or $bound[0].Workspace -ne 'C:\Users\pou\workspaces\lg-magic' -or
    (Get-Service KhadangRouter).Status -ne 'Running') { throw 'Exact running PC binding required' }
$path = Join-Path $bound[0].Workspace 'LG-SUBTASK.json'
if ((Get-Item $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected handoff refused' }
$original = [IO.File]::ReadAllText($path)
$handoff = $original | ConvertFrom-Json
if ($handoff.schema -ne 'lg_magic_subtask_handoff.v1' -or $handoff.workspace -ne $bound[0].Workspace -or
    ($handoff.telegram.native_thread_id -and $handoff.telegram.native_thread_id -ne $ThreadId)) { throw 'Unexpected or conflicting handoff' }
$backup = Join-Path $root ('lg-handoff-before-binding-'+[Guid]::NewGuid().ToString('N')+'.json')
Copy-Item -LiteralPath $path -Destination $backup
$acl = Get-Acl $backup
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
Set-Acl -LiteralPath $backup -AclObject $acl
$handoff.state = 'pc_topic_connected'
$handoff.blocker = $null
$handoff.telegram.topic_id = $Topic
$handoff.telegram.native_thread_id = $ThreadId
$handoff.telegram | Add-Member topic_url ('https://t.me/c/4320138859/'+$Topic) -Force
$handoff.remaining_acceptance = @($handoff.remaining_acceptance | Where-Object {$_ -ne 'PC-side Khadang routing and exact topic/native-session binding'})
$completion = 'PC-only Khadang topic bound to exact durable native Codex thread; native identity/tool/output canary passed'
if ($handoff.completed -notcontains $completion) {$handoff.completed += $completion}
$handoff.constraints = @($handoff.constraints | Where-Object {$_ -ne 'Do not treat this handoff file as an activated relay registry or a working topic'})
$constraint = 'This topic is owner-only. Do not change the protected registry, company authorization, bot credentials or privileged router code.'
if ($handoff.constraints -notcontains $constraint) {$handoff.constraints += $constraint}
if ([IO.File]::ReadAllText($path) -ne $original) { throw 'Handoff changed during inspection; no overwrite' }
[IO.File]::WriteAllText($path,($handoff | ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false))
$verified = [IO.File]::ReadAllText($path) | ConvertFrom-Json
if ($verified.telegram.topic_id -ne $Topic -or $verified.telegram.native_thread_id -ne $ThreadId -or $verified.blocker) { throw 'Binding readback failed' }
[PSCustomObject]@{state=$verified.state;topic=$verified.telegram.topic_url;thread=$ThreadId;backup=$backup} | ConvertTo-Json -Compress
