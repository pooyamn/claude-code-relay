$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'topic-registry.ps1')
$folder=Join-Path ([IO.Path]::GetTempPath()) ('topic-registry-fixture-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $folder|Out-Null
# sqlite3_open_v2 flags=2 deliberately refuses to create a missing file.
$path=Join-Path $folder 'fixture.db';[IO.File]::WriteAllBytes($path,[byte[]]@())
$db=[PcbaRegistry]::new($path)
try{
 $null=$db.Read('CREATE TABLE meta(key TEXT,value TEXT)');$null=$db.Read('CREATE TABLE updates(id INTEGER,payload TEXT,status TEXT)');$null=$db.Read('CREATE TABLE operations(id TEXT,kind TEXT,payload TEXT,status TEXT,result TEXT)')
 $null=$db.Read("INSERT INTO meta VALUES('empty',''),('unicode',CAST(X'F09F9982D8B3D984D8A7D985' AS TEXT)),('null',NULL)")
 $null=$db.Read("INSERT INTO updates VALUES(2,'payload;with:separators','accepted'),(1,'older','retained')")
 $null=$db.Read("INSERT INTO operations VALUES('a','native/thread/resume','{}','unknown',NULL)")
 $legacy=[Text.StringBuilder]::new()
 foreach($sql in @('SELECT * FROM meta ORDER BY key','SELECT * FROM updates ORDER BY id','SELECT * FROM operations ORDER BY id')){
  foreach($row in $db.Read($sql)){foreach($field in $row){if($null -eq $field){$null=$legacy.Append('NULL')}else{$null=$legacy.Append($field.Length.ToString()+':'+$field)};$null=$legacy.Append(';')}}
 }
 $hash=[Security.Cryptography.SHA256]::Create()
 try{$expected=[BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($legacy.ToString()))).Replace('-','')}finally{$hash.Dispose()}
 if($db.UnrelatedDigest() -cne $expected){throw 'Streaming digest must match historical Unicode/null/empty/ordering format'}
 $null=$db.Read("INSERT INTO operations VALUES('b','telegram/sendMessage','{}','unknown',NULL)")
 if($db.UnrelatedDigest() -ceq $expected){throw 'Unrelated mutation must alter digest'}
 'Passed 2 streaming registry audit checks (temporary fixture only; no production access).'
}finally{$db.Dispose()}
# Keep the tiny fixture recoverable for diagnosis; no recursive deletion.
