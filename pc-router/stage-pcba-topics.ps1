param([Parameter(Mandatory=$true)][ValidatePattern('^C:\\ProgramData\\KhadangRouter\\release-[0-9a-f]{32}$')][string]$RecoveryDirectory)
# Fixed migration of two already-created checkpoints; no arbitrary SQL/RPC endpoint.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
 (Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask -TaskName 'Oracova-KhadangStartup').State.ToString() -ne 'Disabled'){throw 'Stopped router and fenced supervisor required'}
if(-not (Test-Path -LiteralPath $RecoveryDirectory) -or (Get-Item -LiteralPath $RecoveryDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal retained deployment directory required'}
$policyPath=Join-Path $root 'config.json';$before=[IO.File]::ReadAllText($policyPath)
if((Get-FileHash $policyPath).Hash -ne '740CD20E8B688A7CC14F8FAA574951F54F6C27C2D56DF0B4F2D352A6F4A204E2' -or
 (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne '84AB5DEA4B368980A0754FB64D23F2ABBE0F63DCADA6EAFDB1F752E1A37E5690'){throw 'Current reviewed code/policy differs'}
$policy=$before|ConvertFrom-Json
if($policy.OwnerId -ne 110123423 -or $policy.BotUsername -ne 'TheKhadangBot' -or $policy.ChatId -ne -1004320138859){throw 'Owner/bot policy differs'}
$bindings=@()
foreach($spec in @(
 @{run='9953fc55f092ce47256b668981d71d1d';topic=18;thread='01a104cc-9a63-7901-8897-abf8aff3dfb3';workspace='/Users/pouya/.openclaw/workspace/ai-hil/hardware/augur-1';handoff='dde3218bb6bad93d10f1ee1c82e56230a6930eb0dc9cd6d4cee4249890ed2193'},
 @{run='e389c66ee495b155dac0e992d44c2233';topic=427;thread='01a104cc-d892-7c52-ba1e-e505edfb13d6';workspace='/Users/pouya/.openclaw/workspace/marginal-requests';handoff='95d990989cd907fb8c1a70354aa0634ad35b43229a7f4913a7d96604157efce7'})){
 $proof=Get-Content ("C:\ProgramData\OracovaNativeRemote\codex-connector-"+$spec.run+'\proof\result.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $binding=$proof.newPcBinding
 if(-not $proof.complete -or -not $proof.handoffPersistedAndReadBack -or $proof.modelsStarted -or $proof.unknownEffects -ne 0 -or
  $proof.handoffSha256 -ne $spec.handoff -or $binding.Chat -ne -1004395661179 -or $binding.Topic -ne $spec.topic -or
  $binding.ThreadId -ne $spec.thread -or $binding.Workspace -ne $spec.workspace -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or
  (Get-ScheduledTask -TaskName ('Oracova-ManagedCodexProof-'+$spec.run)).State.ToString() -ne 'Disabled'){throw 'Exact completed checkpoint proof required'}
 $bindings+=,$binding
}
$routes=@($policy.AdditionalChats|Where-Object {$null -ne $_})
if(@($routes|Where-Object Chat -eq -1004395661179).Count){throw 'PCBA already admitted; reconcile, never replay'}
$policy|Add-Member AdditionalChats (@($routes)+@([ordered]@{Chat=-1004395661179;IsForum=$true})) -Force
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Security.Cryptography;
public sealed class PcbaRegistry : IDisposable {
 IntPtr db;
 [DllImport(@"C:\Windows\System32\winsqlite3.dll",CharSet=CharSet.Ansi)] static extern int sqlite3_open_v2(string path,out IntPtr db,int flags,IntPtr vfs);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll",CharSet=CharSet.Ansi)] static extern int sqlite3_prepare_v2(IntPtr db,string sql,int bytes,out IntPtr statement,IntPtr tail);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_step(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern IntPtr sqlite3_column_text(IntPtr statement,int column);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_column_bytes(IntPtr statement,int column);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_column_count(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_finalize(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_close_v2(IntPtr db);
 public PcbaRegistry() {if(sqlite3_open_v2(@"C:\ProgramData\KhadangRouter\state\router.db",out db,2,IntPtr.Zero)!=0)throw new Exception("Existing ledger open failed");}
 public string[][] Read(string sql) {
  IntPtr stmt=IntPtr.Zero;
  try {
   if(sqlite3_prepare_v2(db,sql,-1,out stmt,IntPtr.Zero)!=0)throw new Exception("Migration statement preparation failed");
   var rows=new List<string[]>();int rc;
   while((rc=sqlite3_step(stmt))==100){var row=new string[sqlite3_column_count(stmt)];
    for(int i=0;i<row.Length;i++){var ptr=sqlite3_column_text(stmt,i);if(ptr==IntPtr.Zero)continue;
     var bytes=new byte[sqlite3_column_bytes(stmt,i)];Marshal.Copy(ptr,bytes,0,bytes.Length);row[i]=Encoding.UTF8.GetString(bytes);}
    rows.Add(row);
   }
   if(rc!=101)throw new Exception("Migration statement failed");return rows.ToArray();
  }finally{if(stmt!=IntPtr.Zero)sqlite3_finalize(stmt);}
 }
 public string UnrelatedDigest() {
  var value=new StringBuilder();
  foreach(var sql in new[]{"SELECT * FROM meta ORDER BY key","SELECT * FROM updates ORDER BY id","SELECT * FROM operations ORDER BY id"})
   foreach(var row in Read(sql))foreach(var field in row)value.Append(field==null?"NULL":field.Length+":"+field).Append(';');
  using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value.ToString()))).Replace("-","");
 }
 public void Dispose(){if(db!=IntPtr.Zero){sqlite3_close_v2(db);db=IntPtr.Zero;}}
}
'@
$exclusive=[IO.File]::Open("$root\state\exclusive.lock",[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$db=$null;$transaction=$false;$policyWritten=$false
try{
 $db=[PcbaRegistry]::new()
 $uncertain=$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown'))+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")
 if([int]$uncertain[0][0] -ne 0){throw 'Unreconciled deliveries; preserve before migration'}
 $prior=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic')
 if($prior.Length -ne 2){throw 'Exactly the existing Web and LG routes required'}
 $old=@($prior|ForEach-Object {$_[0]|ConvertFrom-Json})
 if(@($old|Where-Object {$_.Chat -eq -1003550185469 -and $_.Topic -eq 8660 -and $_.ThreadId -eq '01a104a6-9fce-74a3-bdb0-e6dc04237ce7'}).Count -ne 1 -or
  @($old|Where-Object {$_.Chat -eq -1004320138859 -and $_.Topic -eq 159 -and $_.ThreadId -eq '01a10114-cbad-7a80-ae57-b9af8f8478c7'}).Count -ne 1){throw 'Existing route identity differs'}
 foreach($row in $db.Read("SELECT value FROM meta WHERE key LIKE 'bubble/%'")){$bubble=$row[0]|ConvertFrom-Json
  if($bubble.busy -or $bubble.held -or $bubble.sendUnknown -or @($bubble.pendingResponses).Count){throw 'Active or unreconciled response; do not interrupt'}}
 $unrelated=$db.UnrelatedDigest();$backup=Join-Path $RecoveryDirectory 'previous-router.db'
 if(Test-Path $backup){throw 'Prior snapshot exists; no replay'}
 $null=$db.Read("VACUUM INTO '"+$backup+"'")
 [IO.File]::WriteAllText((Join-Path $RecoveryDirectory 'previous-config.json'),$before,[Text.UTF8Encoding]::new($false))
 $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
 foreach($binding in $bindings){$json=$binding|ConvertTo-Json -Depth 8 -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
  $null=$db.Read("INSERT INTO bindings(chat,topic,payload) VALUES(-1004395661179,"+$binding.Topic+",CAST(X'"+$hex+"' AS TEXT))")}
 $retained=$db.Read('SELECT payload FROM bindings WHERE chat<>-1004395661179 ORDER BY chat,topic')
 if($db.UnrelatedDigest() -ne $unrelated -or ($retained|ConvertTo-Json -Compress) -ne ($prior|ConvertTo-Json -Compress)){throw 'Unrelated data changed'}
 if([IO.File]::ReadAllText($policyPath) -ne $before){throw 'Policy changed during staging'}
 [IO.File]::WriteAllText($policyPath,($policy|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false));$policyWritten=$true
 $null=$db.Read('COMMIT');$transaction=$false
 $receipt=[ordered]@{phase='staged-not-live';bindings=$bindings;existingRoutesPreserved=$true;unrelatedLedgerSha256=$unrelated;
  policySha256=(Get-FileHash $policyPath).Hash;previousLedgerSha256=(Get-FileHash $backup).Hash;modelsStarted=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 [IO.File]::WriteAllText((Join-Path $RecoveryDirectory 'pcba-migration.json'),($receipt|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
 $receipt|ConvertTo-Json -Depth 8 -Compress
}catch{
 if($transaction){$null=$db.Read('ROLLBACK')}
 if($policyWritten -and $transaction){[IO.File]::WriteAllText($policyPath,$before,[Text.UTF8Encoding]::new($false))}
 throw
}finally{if($db){$db.Dispose()};$exclusive.Dispose()}
