param([Parameter(Mandatory=$true)][string]$Mirror,[string]$PreviousMirror,[switch]$Apply)
# Owner-level skill discovery only. No provider settings, service, auth or model.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$mirrorPath=[IO.Path]::GetFullPath($Mirror)
if(-not (Test-Path -LiteralPath $mirrorPath -PathType Container) -or (Get-Item -LiteralPath $mirrorPath).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal generated mirror required'}
$manifest=Get-Content -LiteralPath (Join-Path $mirrorPath '.publish.json') -Raw -Encoding UTF8|ConvertFrom-Json
if($manifest.version -ne 1){throw 'Unsupported skill mirror'}
$ownerHome=[Environment]::GetFolderPath('UserProfile')
$previousPath=$null
if($PreviousMirror){
 $previousPath=[IO.Path]::GetFullPath($PreviousMirror)
 if($previousPath -eq $mirrorPath -or -not (Test-Path -LiteralPath $previousPath -PathType Container) -or (Get-Item -LiteralPath $previousPath).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal distinct previous mirror required'}
 $previous=Get-Content -LiteralPath (Join-Path $previousPath '.publish.json') -Raw -Encoding UTF8|ConvertFrom-Json
 if($previous.version -ne 1){throw 'Previous mirror receipt missing'}
}
$roots=@('.agents\skills','.codex\skills','.claude\skills')|ForEach-Object {Join-Path $ownerHome $_}
$actions=@()
foreach($skill in $manifest.skills.PSObject.Properties){
 if($skill.Name -notmatch '^[a-z0-9][a-z0-9-]{0,63}$' -or $skill.Name -eq 'synced'){throw 'Invalid skill name'}
 $source=Join-Path $mirrorPath $skill.Name
 if((Get-Item -LiteralPath $source).Attributes -band [IO.FileAttributes]::ReparsePoint -or @(Get-ChildItem -LiteralPath $source -Recurse -Force|Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count -or @(Get-ChildItem -LiteralPath $source -Recurse -File -Force).Count -ne @($skill.Value.PSObject.Properties).Count){throw 'Mirror resource layout drift'}
 if(-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md') -PathType Leaf)){throw 'Skill manifest missing'}
 foreach($file in $skill.Value.PSObject.Properties){
  if($file.Name -match '(^/|\\|(^|/)\.\.(/|$)|[:\x00-\x1f])' -or $file.Value -notmatch '^[a-f0-9]{64}$'){throw 'Invalid mirror file'}
  if((Get-FileHash -LiteralPath (Join-Path $source $file.Name)).Hash -ne $file.Value){throw 'Mirror content drift'}
 }
 foreach($root in $roots){
  if(Test-Path -LiteralPath $root){if((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Redirected consumer root'}}
  $destination=Join-Path $root $skill.Name;$ready=$false;$replace=$false;$actual=$null
  if(Test-Path -LiteralPath $destination){
   $item=Get-Item -LiteralPath $destination -Force
   if($item.LinkType -ne 'Junction' -or @($item.Target).Count -ne 1){throw 'Existing skill preserved; resolve collision'}
   $actual=[IO.Path]::GetFullPath($item.Target[0])
   if($actual -eq $source){$ready=$true}
   elseif($previousPath -and $actual -eq (Join-Path $previousPath $skill.Name) -and $previous.skills.PSObject.Properties.Name -contains $skill.Name){
    if(@(Get-ChildItem -LiteralPath $actual -Recurse -File -Force).Count -ne @($previous.skills.($skill.Name).PSObject.Properties).Count -or @(Get-ChildItem -LiteralPath $actual -Recurse -Force|Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count){throw 'Old mirror resources changed; preserved'}
    foreach($oldFile in $previous.skills.($skill.Name).PSObject.Properties){
     if($oldFile.Name -match '(^/|\\|(^|/)\.\.(/|$)|[:\x00-\x1f])' -or $oldFile.Value -notmatch '^[a-f0-9]{64}$' -or (Get-FileHash -LiteralPath (Join-Path $actual $oldFile.Name)).Hash -ne $oldFile.Value){throw 'Old mirror drift; user edits preserved'}
    }
    $replace=$true
   }else{throw 'Existing skill preserved; resolve collision'}
  }elseif(Get-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue){throw 'Broken existing link preserved'}
  $actions+=@{source=$source;destination=$destination;root=$root;ready=$ready;replace=$replace;prior=$actual}
 }
}
# Complete collision/hash preflight before creating any consumer entries.
$backups=@()
if($Apply){foreach($action in $actions|Where-Object {-not $_.ready}){
 [IO.Directory]::CreateDirectory($action.root)|Out-Null
 $saved=$null
 if($action.replace){
  $current=Get-Item -LiteralPath $action.destination -Force
  if($current.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath($current.Target[0]) -ne $action.prior){throw 'Skill link changed since preflight'}
  $snapshot=Join-Path $ownerHome ('.local\share\agent-skills\backups\'+[Guid]::NewGuid().ToString('N'))
  [IO.Directory]::CreateDirectory($snapshot)|Out-Null;$saved=Join-Path $snapshot 'original'
  [IO.File]::WriteAllText((Join-Path $snapshot 'restore.json'),(@{destination=$action.destination;previousTarget=$action.prior}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
  [IO.Directory]::Move($action.destination,$saved);$backups+=$snapshot
 }
 try{New-Item -ItemType Junction -Path $action.destination -Target $action.source -ErrorAction Stop|Out-Null}
 catch{if($saved -and -not (Test-Path -LiteralPath $action.destination)){[IO.Directory]::Move($saved,$action.destination)};throw}
 if(-not (Test-Path -LiteralPath (Join-Path $action.destination 'SKILL.md'))){throw 'Skill publication unreadable'}
}}
@{skills=@($manifest.skills.PSObject.Properties).Count;consumerEntries=$actions.Count;missing=$(if($Apply){0}else{@($actions|Where-Object {-not $_.ready}).Count});applied=[bool]$Apply;ownerHome=$ownerHome;modelsStarted=0;backups=$backups}|ConvertTo-Json -Compress
