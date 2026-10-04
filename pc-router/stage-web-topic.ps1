param([Parameter(Mandatory=$true)][ValidatePattern('^C:\\ProgramData\\KhadangRouter\\release-[0-9a-f]{32}$')][string]$RecoveryDirectory)
# Fixed first-topic migration, not an arbitrary SQL/agent administration API.
# Run only inside the reviewed deployment's stopped-service/startup fence.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or
 -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
 (Get-Service KhadangRouter).Status.ToString() -ne 'Stopped') {throw 'Reviewed administrator deployment with stopped router required'}
if((Get-ScheduledTask -TaskName 'Oracova-KhadangStartup').State.ToString() -ne 'Disabled'){throw 'Startup supervisor must remain fenced'}
if(-not (Test-Path -LiteralPath $RecoveryDirectory) -or (Get-Item -LiteralPath $RecoveryDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal retained deployment directory required'}
$policyPath=Join-Path $root 'config.json'
$before=[IO.File]::ReadAllText($policyPath)
if((Get-FileHash -LiteralPath $policyPath).Hash -ne '653FD4D37637BEA5ED8C88BF063A1669D5A0DCA5E3B6BDD795189D151A2FD2EC'){throw 'Source policy changed; review before migration'}
$policy=$before|ConvertFrom-Json
$connector='C:\ProgramData\OracovaNativeRemote\codex-connector-cbd984bbed3d4784b7254840bc837208'
$created=Get-Content -LiteralPath (Join-Path $connector 'proof\created-native-thread.json') -Raw|ConvertFrom-Json
$binding=$created.binding
if($policy.OwnerId -ne 110123423 -or $policy.BotUsername -ne 'TheKhadangBot' -or $policy.ChatId -ne -1004320138859 -or
 $binding.Chat -ne -1003550185469 -or $binding.Topic -ne 8660 -or
 $binding.ThreadId -ne '01a104a6-9fce-74a3-bdb0-e6dc04237ce7' -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or
 $binding.Workspace -ne '/Users/pouya/.openclaw/workspace/ai-hil/web' -or $created.model -ne 'gpt-6-astra' -or
 $created.handoffSha256 -ne 'd6fe808e29a4ea5854eada96de66c7469ed8e5028c736304f7c03ebe51bda1dd'){throw 'Exact reviewed owner, source policy and created Web checkpoint required'}
$reviewed=Get-Content -LiteralPath (Join-Path $connector 'reviewed-policy.json') -Raw|ConvertFrom-Json
if($reviewed.LinuxCodex.PackageRoot -ne $connector -or $reviewed.LinuxWorkspaceRoot -ne '/Users/pouya/.openclaw/workspace'){throw 'Protected native connector policy differs'}
foreach($entry in $reviewed.LinuxCodex.FileSha256.PSObject.Properties){
 if((Get-FileHash -LiteralPath (Join-Path $connector $entry.Name)).Hash -ne $entry.Value){throw 'Reviewed connector file changed'}
}
if((Get-FileHash 'C:\Windows\System32\wsl.exe').Hash -ne $reviewed.LinuxCodex.WslSha256){throw 'Reviewed WSL image changed'}
$policy|Add-Member LinuxWorkspaceRoot $reviewed.LinuxWorkspaceRoot
$policy|Add-Member LinuxCodex $reviewed.LinuxCodex
$routes=@($policy.AdditionalChats|Where-Object {$null -ne $_})
if(@($routes|Where-Object Chat -eq -1003550185469).Count){throw 'Ai Dispatch already admitted; reconcile instead of reapplying'}
$policy|Add-Member AdditionalChats (@($routes)+@([ordered]@{Chat=-1003550185469;IsForum=$true})) -Force
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Security.Cryptography;
public sealed class WebBindingMigration : IDisposable {
 IntPtr db;
 [DllImport(@"C:\Windows\System32\winsqlite3.dll",CharSet=CharSet.Ansi)] static extern int sqlite3_open_v2(string path,out IntPtr db,int flags,IntPtr vfs);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll",CharSet=CharSet.Ansi)] static extern int sqlite3_prepare_v2(IntPtr db,string sql,int bytes,out IntPtr statement,IntPtr tail);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_step(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern IntPtr sqlite3_column_text(IntPtr statement,int column);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_column_bytes(IntPtr statement,int column);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_column_count(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_finalize(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_close_v2(IntPtr db);
 public WebBindingMigration() {
  if(sqlite3_open_v2(@"C:\ProgramData\KhadangRouter\state\router.db",out db,2,IntPtr.Zero)!=0)throw new Exception("Existing ledger open failed");
 }
 public string[][] Read(string sql) {
  IntPtr stmt=IntPtr.Zero;
  try {
   if(sqlite3_prepare_v2(db,sql,-1,out stmt,IntPtr.Zero)!=0)throw new Exception("Migration statement preparation failed");
   var rows=new List<string[]>();int rc;
   while((rc=sqlite3_step(stmt))==100){
    var row=new string[sqlite3_column_count(stmt)];
    for(int i=0;i<row.Length;i++){
     var ptr=sqlite3_column_text(stmt,i);if(ptr==IntPtr.Zero)continue;
     var bytes=new byte[sqlite3_column_bytes(stmt,i)];Marshal.Copy(ptr,bytes,0,bytes.Length);row[i]=Encoding.UTF8.GetString(bytes);
    }
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
$exclusive=[IO.File]::Open((Join-Path $root 'state\exclusive.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$db=$null;$transaction=$false;$policyWritten=$false
try{
 $db=[WebBindingMigration]::new()
 $uncertain=$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown'))+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")
 if([int]$uncertain[0][0] -ne 0){throw 'Pending or uncertain deliveries exist; preserve and reconcile'}
 $prior=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic')
 if($prior.Length -ne 1){throw 'Expected exactly the existing LG route; preserve unexpected bindings'}
 $lg=$prior[0][0]|ConvertFrom-Json
 if($lg.Chat -ne -1004320138859 -or $lg.Topic -ne 159 -or $lg.ThreadId -ne '01a10114-cbad-7a80-ae57-b9af8f8478c7'){throw 'Existing LG identity differs'}
 foreach($row in $db.Read("SELECT value FROM meta WHERE key LIKE 'bubble/%'")){
  $bubble=$row[0]|ConvertFrom-Json
  if($bubble.busy -or $bubble.held -or $bubble.sendUnknown -or @($bubble.pendingResponses).Count){throw 'A native response is active or held; do not interrupt'}
 }
 $unrelated=$db.UnrelatedDigest()
 $backup=Join-Path $RecoveryDirectory 'previous-router.db'
 if(Test-Path -LiteralPath $backup){throw 'Prior migration snapshot exists; no replay'}
 # SQLite creates a consistent standalone backup, including committed WAL.
 $null=$db.Read("VACUUM INTO '"+$backup+"'")
 [IO.File]::WriteAllText((Join-Path $RecoveryDirectory 'previous-config.json'),$before,[Text.UTF8Encoding]::new($false))
 $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
 $json=$binding|ConvertTo-Json -Depth 8 -Compress
 $hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
 $null=$db.Read("INSERT INTO bindings(chat,topic,payload) VALUES(-1003550185469,8660,CAST(X'"+$hex+"' AS TEXT))")
 if($db.UnrelatedDigest() -ne $unrelated -or $db.Read('SELECT payload FROM bindings WHERE chat=-1004320138859 AND topic=159')[0][0] -ne $prior[0][0]){
  throw 'Unrelated ledger content changed; rollback required'
 }
 if([IO.File]::ReadAllText($policyPath) -ne $before){throw 'Policy changed during migration'}
 [IO.File]::WriteAllText($policyPath,($policy|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false));$policyWritten=$true
 $null=$db.Read('COMMIT');$transaction=$false
 $receipt=[ordered]@{phase='staged-not-live';binding=$binding;existingLgPreserved=$true;unrelatedLedgerSha256=$unrelated;
  policySha256=(Get-FileHash $policyPath).Hash;previousLedgerSha256=(Get-FileHash $backup).Hash;
  sourceRouteChanged=$false;modelsStarted=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 [IO.File]::WriteAllText((Join-Path $RecoveryDirectory 'web-migration.json'),($receipt|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
 $receipt|ConvertTo-Json -Depth 8 -Compress
}catch{
 if($transaction){$null=$db.Read('ROLLBACK')}
 if($policyWritten -and $transaction){[IO.File]::WriteAllText($policyPath,$before,[Text.UTF8Encoding]::new($false))}
 throw
}finally{if($db){$db.Dispose()};$exclusive.Dispose()}
