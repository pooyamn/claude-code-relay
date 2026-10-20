# Regression for native powershell.exe -File switch argument serialization.
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'run-topic-request.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner parse failed'}
$function=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'InvokeHelper'},$true)
if(-not $function){throw 'Helper function missing'}
. ([ScriptBlock]::Create($function.Extent.Text))
$package=Join-Path ([IO.Path]::GetTempPath()) ('topic-argument-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $package|Out-Null
$fixture=Join-Path $package 'fixture.ps1'
[IO.File]::WriteAllText($fixture, @'
param([switch]$PreflightOnly,[switch]$RetryPreflight,[string]$Name,[long]$ChatId)
@{preflight=[bool]$PreflightOnly;retry=[bool]$RetryPreflight;name=$Name;chat=$ChatId}|ConvertTo-Json -Compress
'@, [Text.UTF8Encoding]::new($false))
try{
 $result=(InvokeHelper 'fixture.ps1' @{PreflightOnly=$true;RetryPreflight=$false;Name='Motorcontrol Plant';ChatId=[long]-1003550185469})|ConvertFrom-Json
 if(-not $result.preflight -or $result.retry -or $result.name -cne 'Motorcontrol Plant' -or $result.chat -ne -1003550185469){throw 'Boolean/native quoted arguments regressed'}
 $result=(InvokeHelper 'fixture.ps1' @{PreflightOnly=[Management.Automation.SwitchParameter]::new($false);RetryPreflight=[Management.Automation.SwitchParameter]::new($true);Name='Fresh topic';ChatId=[long]-1004395661179})|ConvertFrom-Json
 if($result.preflight -or -not $result.retry -or $result.name -cne 'Fresh topic' -or $result.chat -ne -1004395661179){throw 'SwitchParameter arguments regressed'}
 @{passed=$true;cases=2;topicsCreated=0;modelsStarted=0}|ConvertTo-Json -Compress
}finally{
 [IO.File]::Delete($fixture)
 [IO.Directory]::Delete($package)
}
