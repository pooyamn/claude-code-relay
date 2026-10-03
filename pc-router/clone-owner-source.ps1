param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit,
 [ValidatePattern('^C:\\ProgramData\\OracovaNativeRemote\\router-source-[0-9a-f]{32}\.bundle$')][string]$Bundle,
 [ValidatePattern('^[0-9a-fA-F]{64}$')][string]$BundleSha256
)
# One-shot ordinary-owner clone. Never run Git/GH or user credential helpers as
# administrator; no models, login flow, global configuration, replay or overwrite.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
$session=[Diagnostics.Process]::GetCurrentProcess().SessionId
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or
 $identity.User.Value -ne 'S-1-5-21-71459778-1164188569-2276148161-1001' -or
 $identity.IsSystem -or $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $session -eq 0){
 throw 'Exact non-elevated interactive PC owner required'
}
$git='C:\Program Files\Git\cmd\git.exe';$gh='C:\Program Files\GitHub CLI\gh.exe'
if((Get-FileHash $git).Hash -ne '78211C7ED73988DA93A6D8A33D47EC6187F464D7EA2A9A00C182BBD7A1ECF30F' -or
 (Get-FileHash $gh).Hash -ne '756724853CC579510B58E65E7A7429AD6B1AF29CF99EF19B3A95F3B701C5C580'){
 throw 'Reviewed Git/GH executable digest mismatch'
}
$parent='C:\Users\pou\workspaces';$destination=Join-Path $parent 'claude-code-relay'
$state=Join-Path 'C:\Users\pou\.native-remote' ('source-clone-'+$RunId)
if([bool]$Bundle -ne [bool]$BundleSha256){throw 'Bundle path and reviewed digest required together'}
if($Bundle -and ((Get-Item -LiteralPath $Bundle).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Literal sealed source bundle required'}
if($Bundle -and (Get-FileHash -LiteralPath $Bundle).Hash -ne $BundleSha256){throw 'Reviewed source bundle digest mismatch'}
foreach($root in @($parent,'C:\Users\pou\.native-remote')){
 for($part=[IO.DirectoryInfo]::new($root);$null -ne $part;$part=$part.Parent){
  if(-not $part.Exists -or ($part.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Existing literal owner directories required'}
 }
}
if((Test-Path -LiteralPath $state) -or (Test-Path -LiteralPath $destination)){throw 'Prior state/destination exists; inspect it, never replay or overwrite'}
[IO.Directory]::CreateDirectory($state) | Out-Null
$claim=[IO.File]::Open((Join-Path $state 'one-shot.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try{$claim.Flush($true)}finally{$claim.Dispose()}
$clock=[Diagnostics.Stopwatch]::StartNew()
function Invoke-SourceCommand([string]$Exe,[string]$Arguments,[string]$Label){
 $info=[Diagnostics.ProcessStartInfo]::new($Exe,$Arguments)
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.WorkingDirectory=$parent
 $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true;$info.RedirectStandardInput=$true
 $info.EnvironmentVariables['PATH']='C:\Program Files\Git\cmd;C:\Program Files\GitHub CLI;C:\Windows\System32;C:\Windows'
 $info.EnvironmentVariables['GIT_TERMINAL_PROMPT']='0';$info.EnvironmentVariables['GCM_INTERACTIVE']='Never'
 $info.EnvironmentVariables['GH_PROMPT_DISABLED']='1'
 $child=[Diagnostics.Process]::Start($info);$child.StandardInput.Close()
 $stdout=$child.StandardOutput.ReadToEndAsync();$stderr=$child.StandardError.ReadToEndAsync()
 $remaining=[Math]::Max(1,120000-[int]$clock.ElapsedMilliseconds)
 if(-not $child.WaitForExit($remaining)){
  # Only this exact owned process tree, never native remote/router processes.
  & 'C:\Windows\System32\taskkill.exe' /PID $child.Id /T /F 2>$null | Out-Null
  throw ($Label+'DeadlineExceeded; partial clone retained, no automatic retry')
 }
 $out=$stdout.GetAwaiter().GetResult();$err=$stderr.GetAwaiter().GetResult()
 [IO.File]::WriteAllText((Join-Path $state ($Label+'.stdout.private')),$out)
 [IO.File]::WriteAllText((Join-Path $state ($Label+'.stderr.private')),$err)
 if($child.ExitCode -ne 0){throw ($Label+'Exit='+$child.ExitCode+'; inspect private output, no automatic login/retry')}
 return $out.Trim()
}
$report=[ordered]@{schema='ccrelay.owner_source_clone.v1';at=$null;run=$RunId;ownerSid=$identity.User.Value;
 windowsElevated=$false;sessionId=$session;repository='pooyamn/claude-code-relay';destination=$destination;
 branch='codex/agentic-pc-preparation';expectedCommit=$ExpectedCommit;actualCommit=$null;complete=$false;
 transport=$(if($Bundle){'reviewed-local-git-bundle'}else{'github-cli'});bundleSha256=$BundleSha256;
 modelsStarted=$false;globalConfigChanged=$false;reviewMergeDeployAuthority=$false;error=$null}
try{
 if($Bundle){
  # Transport workaround: existing GitHub login was rejected with HTTP 401.
  # Transfer repository bytes,
  # not credentials: a digest-pinned --all bundle preserves reachable history.
  # This does not repair GitHub authentication or include uncommitted Mac files.
  $null=Invoke-SourceCommand $git ('clone --branch codex/agentic-pc-preparation "'+$Bundle+'" "'+$destination+'"') 'clone'
  $null=Invoke-SourceCommand $git ('-C "'+$destination+'" remote set-url origin https://github.com/pooyamn/claude-code-relay') 'remote'
 }else{
  $null=Invoke-SourceCommand $gh ('repo clone https://github.com/pooyamn/claude-code-relay "'+$destination+'" --no-upstream -- --branch codex/agentic-pc-preparation') 'clone'
 }
 $report.actualCommit=Invoke-SourceCommand $git ('-C "'+$destination+'" rev-parse HEAD') 'head'
 if($report.actualCommit -ne $ExpectedCommit){throw 'ExpectedCommitMismatch; clone retained, no force reset'}
 $branch=Invoke-SourceCommand $git ('-C "'+$destination+'" branch --show-current') 'branch'
 if($branch -ne $report.branch){throw 'ExpectedBranchMismatch'}
 $shallow=Invoke-SourceCommand $git ('-C "'+$destination+'" rev-parse --is-shallow-repository') 'shallow'
 if($shallow -ne 'false'){throw 'Full history required'}
 $report.complete=$true
}catch{$report.error=$_.Exception.Message}
$report.at=[DateTime]::UtcNow.ToString('o')
[IO.File]::WriteAllText((Join-Path $state 'result.json'),($report | ConvertTo-Json -Compress))
if(-not $report.complete){exit 1}
exit 0
