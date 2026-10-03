$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$root = 'C:\ProgramData\KhadangRouter'
# Read-only receipt inspection. Never expose credential files, account details,
# arbitrary incoming messages or operation request payloads.
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class RouterReceipts {
 [DllImport(@"C:\Windows\System32\winsqlite3.dll",CharSet=CharSet.Ansi)] static extern int sqlite3_open_v2(string path,out IntPtr db,int flags,IntPtr vfs);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll",CharSet=CharSet.Ansi)] static extern int sqlite3_prepare_v2(IntPtr db,string sql,int bytes,out IntPtr statement,IntPtr tail);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_step(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern IntPtr sqlite3_column_text(IntPtr statement,int column);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_column_bytes(IntPtr statement,int column);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_column_count(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_finalize(IntPtr statement);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")] static extern int sqlite3_close_v2(IntPtr db);
 public static string[][] Read(string sql) {
   IntPtr db,stmt=IntPtr.Zero;
   if(sqlite3_open_v2(@"C:\ProgramData\KhadangRouter\state\router.db",out db,1,IntPtr.Zero)!=0)throw new Exception("Read-only database open failed");
   try {
     if(sqlite3_prepare_v2(db,sql,-1,out stmt,IntPtr.Zero)!=0)throw new Exception("Receipt query failed");
     var rows=new List<string[]>(); int code;
     while((code=sqlite3_step(stmt))==100) {
       var row=new string[sqlite3_column_count(stmt)];
       for(int i=0;i<row.Length;i++) {
         var pointer=sqlite3_column_text(stmt,i); if(pointer==IntPtr.Zero)continue;
         var bytes=new byte[sqlite3_column_bytes(stmt,i)]; Marshal.Copy(pointer,bytes,0,bytes.Length);
         row[i]=Encoding.UTF8.GetString(bytes);
       }
       rows.Add(row);
     }
     if(code!=101)throw new Exception("Receipt read failed");
     return rows.ToArray();
   } finally {if(stmt!=IntPtr.Zero)sqlite3_finalize(stmt);sqlite3_close_v2(db);}
 }
}
'@
$service = Get-CimInstance Win32_Service | Where-Object Name -eq 'KhadangRouter'
$report = [ordered]@{host=$env:COMPUTERNAME;service=$service.State;startup=$service.StartMode}
foreach ($name in @('probe','status','failure')) {
    $path = Join-Path $root ('state\'+$name+'.json')
    if (Test-Path $path) {$report[$name]=Get-Content $path -Raw | ConvertFrom-Json}
}
$report.receipts = @([RouterReceipts]::Read('SELECT kind,status,COUNT(*) FROM operations GROUP BY kind,status') | ForEach-Object {
    [PSCustomObject]@{kind=$_[0];status=$_[1];count=[int]$_[2]}
})
$report.metadata = @([RouterReceipts]::Read("SELECT key,value FROM meta WHERE key IN ('lg-provision','native-canary') OR key LIKE 'bubble/%'") | ForEach-Object {
    [PSCustomObject]@{key=$_[0];value=($_[1] | ConvertFrom-Json)}
})
$report.bindings = @([RouterReceipts]::Read('SELECT payload FROM bindings') | ForEach-Object {$_[0] | ConvertFrom-Json})
$report.nativeRejections = @([RouterReceipts]::Read("SELECT kind,result FROM operations WHERE status='rejected' AND kind LIKE 'native/%' ORDER BY rowid DESC LIMIT 5") | ForEach-Object {
    [PSCustomObject]@{kind=$_[0];error=$(if ($_[1]) {$_[1] | ConvertFrom-Json} else {'No detailed error receipt in this historical record'})}
})
$report | ConvertTo-Json -Depth 12
