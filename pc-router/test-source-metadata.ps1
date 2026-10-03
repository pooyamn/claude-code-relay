$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$source=Join-Path $PSScriptRoot 'clone-owner-source.ps1'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Source update helper parse failed'}
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-LiteralSource'},$true)
if(-not $function){throw 'Actual source metadata guard required'}
. ([ScriptBlock]::Create($function.Extent.Text))
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('oracova-source-metadata-'+[Guid]::NewGuid().ToString('N'))
$git=Join-Path $fixture '.git';$link=Join-Path $fixture 'junction';$checks=0
function Assert([bool]$Value,[string]$Name){if(-not $Value){throw $Name};$script:checks++}
[IO.Directory]::CreateDirectory($git)|Out-Null
[IO.File]::SetAttributes($git,([IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::Directory))
try{
 Assert ([IO.Directory]::Exists($git)) 'Actual hidden Git directory exists'
 try{$null=Get-Item -LiteralPath $git;throw 'Hidden directory unexpectedly visible without Force'}catch{Assert ($_.Exception.Message -ne 'Hidden directory unexpectedly visible without Force') 'Actual default metadata lookup reproduces hidden-directory failure'}
 Assert-LiteralSource $git;Assert $true 'Production metadata guard accepts literal hidden Git directory'
 Assert ((([IO.DirectoryInfo]::new($git)).Attributes -band [IO.FileAttributes]::Hidden) -ne 0) 'Source hidden attribute is unchanged'
 & $env:ComSpec /d /c ('mklink /J "'+$link+'" "'+$git+'"')|Out-Null
 if($LASTEXITCODE -ne 0){throw 'Actual NTFS junction fixture failed'}
 try{Assert-LiteralSource $link;throw 'Source junction accepted'}catch{Assert ($_.Exception.Message -eq 'Literal existing repository required') 'Hidden metadata visibility does not admit a redirected source'}
 [Console]::WriteLine(('All '+$checks+' Windows source-metadata checks passed; no real repository/credentials/network/models.'))
}finally{
 # Only the exact generated fixture-owned junction, then its new test tree.
 if(Test-Path -LiteralPath $link){[IO.Directory]::Delete($link)}
 [IO.Directory]::Delete($fixture,$true)
}
