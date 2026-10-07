param([ValidateSet('Inspect','Apply')][string]$Mode='Inspect')
# Run only after this generation and all executable inputs are reviewed/sealed.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
foreach($path in @($PSScriptRoot,(Join-Path $PSScriptRoot 'watchdog.ps1'),(Join-Path $PSScriptRoot 'health_probe.py'),(Join-Path $PSScriptRoot 'always-on-policy.ps1'))){
 $item=Get-Item -LiteralPath $path;$acl=Get-Acl -LiteralPath $path
 if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $admin.Value){throw 'Administrator-owned nonredirected code required'}
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin @($admin.Value,$system.Value) -and
   ([int]$rule.FileSystemRights -band 0xD0156)){throw 'Unprivileged executable mutation denied'}
 }
}
$tasks=@('Oracova-MTProtoHealth','Oracova-AlwaysOnPolicy')
$before=@(foreach($name in $tasks){
 $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
 [pscustomobject]@{name=$name;exists=($null -ne $task);state=if($task){$task.State.ToString()}else{'absent'}}
})
if($Mode -eq 'Inspect'){$before|ConvertTo-Json -Compress;return}
foreach($t in $before){
 if($t.exists){
  Export-ScheduledTask -TaskName $t.name|Out-File -LiteralPath (Join-Path $PSScriptRoot ($t.name+'-before.xml')) -NoClobber -Encoding UTF8
  # Existing unrelated task must never be silently commandeered.
  $existing=Get-ScheduledTask -TaskName $t.name
  if($existing.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or @($existing.Actions).Count -ne 1 -or
    $existing.Actions[0].Arguments -notlike '*C:\ProgramData\OracovaMTProtoHealth-*'){throw 'Unexpected existing watchdog; preserve'}
 }
}
& 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'always-on-policy.ps1') -Mode Apply
if($LASTEXITCODE -ne 0){throw 'Always-on policy failed'}
$principal=New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
foreach($name in $tasks){
 $filename=if($name -eq 'Oracova-MTProtoHealth'){'watchdog.ps1'}else{'always-on-policy.ps1'}
 $extra=if($name -eq 'Oracova-AlwaysOnPolicy'){' -Mode Guard'}else{''}
 $action=New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $PSScriptRoot $filename)+'"'+$extra)
 $minutes=if($name -eq 'Oracova-MTProtoHealth'){1}else{5}
 $boot=New-ScheduledTaskTrigger -AtStartup
 $repeat=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval ([TimeSpan]::FromMinutes($minutes))
 $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromSeconds(110)) -RestartCount 3 -RestartInterval ([TimeSpan]::FromMinutes(1))
 Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Trigger @($boot,$repeat) -Settings $settings -Force|Out-Null
 Start-ScheduledTask -TaskName $name
}
$before|ConvertTo-Json -Compress|Out-File -LiteralPath (Join-Path $PSScriptRoot 'tasks-before.json') -NoClobber -Encoding UTF8
[pscustomobject]@{installed=$tasks;servicesReconfigured=$false;credentialsChanged=$false;firmwareChanged=$false;nextBootVerified=$false}|ConvertTo-Json -Compress
