param([ValidateSet('prepare','run')][string]$Phase='prepare', [string]$NativeResultHash)
# One approved request, not a new participant provisioning grant. Reuse the
# installed reviewed workflow; preserve its receipt, proof and restart guards.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$native='C:\ProgramData\OracovaNativeRemote';$root='C:\ProgramData\KhadangRouter'
$package="$native\topic-trivial-approved-20261115";$original="$native\topic-automation-20261013"
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Existing administrator maintenance required'}
$f="$native\inspect-state.ps1"
if((Get-FileHash $f).Hash -ne 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'){throw 'Inspector changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($f,[ref]$null,[ref]$null)
$def=$ast.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class RouterReceipts*'},$true)
if(-not ('RouterReceipts' -as [type])){& ([scriptblock]::Create($def.Extent.Text))}
$p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
if($p.OwnerId -ne 110123423 -or $p.BotId -ne 8735489806){throw 'Owner/bot changed'}
$source=[RouterReceipts]::Read("SELECT payload FROM bindings WHERE chat=-1004395661179 AND topic=427")
if($source.Length -ne 1 -or ($source[0][0]|ConvertFrom-Json).ThreadId -ne '01a104cc-d892-7c52-ba1e-e505edfb13d6'){throw 'Protected source changed'}
$requestRows=[RouterReceipts]::Read('SELECT status,payload FROM updates WHERE id=759325548')
$approvalRows=[RouterReceipts]::Read('SELECT status,payload FROM updates WHERE id=759325549')
if($requestRows.Length -ne 1 -or $approvalRows.Length -ne 1 -or $requestRows[0][0] -ne 'accepted' -or $approvalRows[0][0] -ne 'accepted'){throw 'Retained request and approval required'}
$request=($requestRows[0][1]|ConvertFrom-Json).message;$approval=($approvalRows[0][1]|ConvertFrom-Json).message
foreach($m in @($request,$approval)){if($m.from.is_bot -or $m.forward_origin -or $m.forward_date -or $m.sender_chat -or $m.via_bot -or $m.chat.id -ne -1004395661179 -or $m.message_thread_id -ne 427){throw 'Original same-topic human messages required'}}
if($request.from.id -ne 199200674 -or $request.message_id -ne 5555 -or $request.text -cne 'Create a new fresh topic and call it "Trivial Topics". It''s independent of other topics, no shared memory or inheritance from others.' -or $approval.from.id -ne $p.OwnerId -or $approval.message_id -ne 5558 -or $approval.text -cne 'Approved' -or $approval.date -lt $request.date){throw 'Exact request-specific owner approval required'}
function WriteUtf8($path,$text){[IO.File]::WriteAllText($path,$text,[Text.UTF8Encoding]::new($false))}
if($Phase -eq 'prepare'){
 if(Test-Path $package){throw 'Existing package: inspect, do not recreate'}
 $manifest=[IO.File]::ReadAllText("$original\package.json")|ConvertFrom-Json
 foreach($file in $manifest.files.PSObject.Properties){if((Get-FileHash (Join-Path $original $file.Name)).Hash -ne $file.Value){throw 'Installed workflow changed'}}
 New-Item -ItemType Directory $package|Out-Null;Set-Acl $package (Get-Acl $original)
 foreach($file in $manifest.files.PSObject.Properties){Copy-Item (Join-Path $original $file.Name) (Join-Path $package $file.Name)}
 # Scope the two existing request-name checks to the approved source update.
 # The outer wrapper verifies the separate, verbatim participant request above.
 foreach($name in @('run-topic-request.ps1','enroll-codex-topic-fast.ps1')){
  $path=Join-Path $package $name;$text=[IO.File]::ReadAllText($path)
  $find=$(if($name -eq 'run-topic-request.ps1'){'$message.text -notmatch [regex]::Escape($Name)'}else{'$request.text -notmatch [regex]::Escape($created.name)'})
  $replace=$(if($name -eq 'run-topic-request.ps1'){'($SourceUpdate -ne 759325549 -or $Name -cne ''Trivial Topics'' -or $message.text -cne ''Approved'')'}else{'($SourceUpdate -ne 759325549 -or $created.name -cne ''Trivial Topics'' -or $request.text -cne ''Approved'')'})
  if(($text.Split([string[]]@($find),[StringSplitOptions]::None)).Length -ne 2){throw 'Expected single authorization check'}
  $text=$text.Replace($find,$replace)
  if($name -eq 'run-topic-request.ps1'){
   # Allocate through the existing ordinary-owner Linux connection, not elevated
   # SSH -> WSL. Consume its hash-verified protected result exactly once.
   $pattern='(?s) \$receipt=''/Users/pouya/\.migration/topic-request-''\+\$SourceUpdate.*? \$ThreadId=\$nativeResult.thread'
   if([regex]::Matches($text,$pattern).Count -ne 1){throw 'Expected single allocation block'}
   $replacement=' $nativeResult=[IO.File]::ReadAllText("$package\prepared-native.json")|ConvertFrom-Json'+"`n"+
    ' if(-not $nativeResult.complete -or $nativeResult.unknownEffects -ne 0 -or $nativeResult.modelsStarted -ne 0 -or $nativeResult.nativeOwnerUid -ne 1000 -or $nativeResult.sourceUpdate -ne 759325549 -or $nativeResult.workspace -cne $Workspace -or $nativeResult.name -cne $Name -or $nativeResult.chat -ne $source.Chat -or -not $nativeResult.checkpointPersisted){throw ''Prepared ordinary-owner allocation differs''}'+"`n"+' $ThreadId=$nativeResult.thread'
   $text=[regex]::Replace($text,$pattern,[Text.RegularExpressions.MatchEvaluator]{param($m)$replacement})
  }
  $tokens=$null;$errors=$null;$null=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
  if($errors.Count){throw 'Adapted workflow parse failure'}
  WriteUtf8 $path $text
 }
 foreach($file in $manifest.files.PSObject.Properties){$file.Value=(Get-FileHash (Join-Path $package $file.Name)).Hash}
 WriteUtf8 "$package\package.json" ($manifest|ConvertTo-Json -Depth 8)
 WriteUtf8 "$package\approval.json" (@{requestId='topic-trivial-20261115-marginal';requestUpdate=759325548;ownerApprovalUpdate=759325549;controllerApprovalUpdate=759325550;name='Trivial Topics';source=$source[0][0];isolation='fresh separate workspace; no imported history or memory';scope='this request only'}|ConvertTo-Json -Depth 5)
 & "$package\run-topic-request.ps1" -Name 'Trivial Topics' -SourceUpdate 759325549 -SourceThreadId 01a104cc-d892-7c52-ba1e-e505edfb13d6 -Backend codex -Workspace /Users/pouya/.openclaw/workspace/trivial-topics -Mode fresh -PreflightOnly
 return
}
if($Phase -eq 'run'){
 if($NativeResultHash -notmatch '^[a-fA-F0-9]{64}$'){throw 'Reviewed ordinary-owner result hash required'}
 $inputPath='C:\Users\pou\AppData\Local\Temp\trivial-topics-native-20261115.json'
 $bytes=[IO.File]::ReadAllBytes($inputPath)
 if([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-','') -ne $NativeResultHash){throw 'Ordinary-owner result changed'}
 if(Test-Path "$package\prepared-native.json"){throw 'Prior run result exists: reconcile, never retry'}
 WriteUtf8 "$package\prepared-native.json" ([Text.Encoding]::UTF8.GetString($bytes))
 & "$package\run-topic-request.ps1" -Name 'Trivial Topics' -SourceUpdate 759325549 -SourceThreadId 01a104cc-d892-7c52-ba1e-e505edfb13d6 -Backend codex -Workspace /Users/pouya/.openclaw/workspace/trivial-topics -Mode fresh
 return
}
