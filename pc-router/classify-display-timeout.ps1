param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Intent,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$PayloadSha256,
 [Parameter(Mandatory=$true)][long]$Chat,
 [Parameter(Mandatory=$true)][ValidateRange(1,2147483647)][int]$Message
)
$ErrorActionPreference='Stop'
# Narrow live repair: classify a known-message display edit, NOT confirm it.
# Never read credentials, call Telegram, retry input, change bindings or restart.
$identity=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator maintenance lane required'}
$root='C:\ProgramData\KhadangRouter'
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne 'C22B67C902C7303DFFFB28684CC5CD9183410065FEF909D4C965BE13C3DA31CF' -or
 (Get-FileHash "$root\config.json").Hash -ne '4DD5478914BB7B017D7E9AFF12BBCAEF486AF1DED9B2A13A588B2D0D02C1E923'){
 throw 'Reviewed live release changed; no classification'
}
$service=Get-Service KhadangRouter
if($service.Status -ne 'Running'){throw 'Running service required; no restart recovery'}
# Reuse the already installed, protected OS-SQLite maintenance implementation.
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('C:\ProgramData\OracovaNativeRemote\stage-dut-topic.ps1',[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Protected maintenance implementation did not parse'}
$definition=$ast.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class PcbaRegistry*'},$true)
if(-not $definition){throw 'Protected OS-SQLite implementation missing'}
& ([ScriptBlock]::Create($definition.Extent.Text))
$db=[PcbaRegistry]::new();$transaction=$false
try{
 $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
 $rows=$db.Read("SELECT kind,payload,status,result FROM operations WHERE id='$Intent'")
 if($rows.Count -ne 1 -or $rows[0][0] -cne 'telegram/editMessageText' -or $rows[0][2] -cne 'unknown'){
  throw 'Only one exact unknown display-edit intent may be classified'
 }
 $payload=$rows[0][1];$p=$payload|ConvertFrom-Json
 $sha=[Security.Cryptography.SHA256]::Create()
 try{$digest=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($payload))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
 if($digest -cne $PayloadSha256 -or $p.chat_id -ne $Chat -or $p.message_id -ne $Message){throw 'Reviewed exact message/payload changed'}
 $known=$db.Read("SELECT COUNT(*) FROM operations WHERE kind='telegram/sendMessage' AND status='confirmed' AND json_extract(result,'$.chat.id')=$Chat AND json_extract(result,'$.message_id')=$Message")
 if([int]$known[0][0] -ne 1){throw 'The original existing message has no unique confirmed send receipt'}
 $audit=[ordered]@{schema='ccrelay.presentation_timeout_classification.v1';intent=$Intent;kind=$rows[0][0];payload=$p;
  payloadSha256=$digest;previousStatus='unknown';newStatus='unknown-presentation';previousResult=$rows[0][3];
  deliveryConfirmed=$false;replayed=$false;nativeProcessesRestarted=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 $json=$audit|ConvertTo-Json -Depth 20 -Compress
 $hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
 $key="presentation-timeout/$Intent"
 if($db.Read("SELECT value FROM meta WHERE key='$key'").Count){throw 'Classification already exists; no repeat'}
 $null=$db.Read("INSERT INTO meta(key,value) VALUES('$key',CAST(X'$hex' AS TEXT))")
 $null=$db.Read("UPDATE operations SET status='unknown-presentation' WHERE id='$Intent' AND kind='telegram/editMessageText' AND status='unknown'")
 $verified=$db.Read("SELECT kind,payload,status,result FROM operations WHERE id='$Intent'")
 if($verified.Count -ne 1 -or $verified[0][0] -cne $rows[0][0] -or $verified[0][1] -cne $payload -or
  $verified[0][2] -cne 'unknown-presentation' -or $verified[0][3] -cne $rows[0][3]){throw 'Only the intended classification may change'}
 $null=$db.Read('COMMIT');$transaction=$false
 $unknown=$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status='unknown')+(SELECT COUNT(*) FROM updates WHERE status='unknown')")
 [ordered]@{intent=$Intent;chat=$Chat;message=$Message;status='unknown-presentation';globalUnknown=[int]$unknown[0][0];
  deliveryConfirmed=$false;replayed=$false;nativeProcessesRestarted=$false;at=$audit.at}|ConvertTo-Json -Compress
}catch{if($transaction){$null=$db.Read('ROLLBACK')};throw}finally{$db.Dispose()}
