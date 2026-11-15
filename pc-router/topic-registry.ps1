# Streaming audit: never materialize the complete multi-GB ledger in memory.
Add-Type @'
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
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
 public PcbaRegistry() : this(@"C:\ProgramData\KhadangRouter\state\router.db") {}
 public PcbaRegistry(string path) {if(sqlite3_open_v2(path,out db,2,IntPtr.Zero)!=0)throw new Exception("Existing registry open failed");}
 static byte[] Field(IntPtr statement,int column) {
  var pointer=sqlite3_column_text(statement,column);if(pointer==IntPtr.Zero)return null;
  var bytes=new byte[sqlite3_column_bytes(statement,column)];Marshal.Copy(pointer,bytes,0,bytes.Length);return bytes;
 }
 public string[][] Read(string sql) {
  IntPtr statement=IntPtr.Zero;
  try {
   if(sqlite3_prepare_v2(db,sql,-1,out statement,IntPtr.Zero)!=0)throw new Exception("Registry statement preparation failed");
   var rows=new List<string[]>();int rc;
   while((rc=sqlite3_step(statement))==100){var row=new string[sqlite3_column_count(statement)];
    for(int i=0;i<row.Length;i++){var bytes=Field(statement,i);row[i]=bytes==null?null:Encoding.UTF8.GetString(bytes);}rows.Add(row);
   }
   if(rc!=101)throw new Exception("Registry statement failed");return rows.ToArray();
  }finally{if(statement!=IntPtr.Zero)sqlite3_finalize(statement);}
 }
 static void Append(HashAlgorithm hash,byte[] bytes){if(bytes.Length!=0)hash.TransformBlock(bytes,0,bytes.Length,bytes,0);}
 public string UnrelatedDigest() {
  using(var hash=SHA256.Create()){
   foreach(var sql in new[]{"SELECT * FROM meta ORDER BY key","SELECT * FROM updates ORDER BY id","SELECT * FROM operations ORDER BY id"}){
    IntPtr statement=IntPtr.Zero;
    try{
     if(sqlite3_prepare_v2(db,sql,-1,out statement,IntPtr.Zero)!=0)throw new Exception("Audit statement preparation failed");
     int rc;while((rc=sqlite3_step(statement))==100){
      for(int column=0;column<sqlite3_column_count(statement);column++){
       var bytes=Field(statement,column);
       if(bytes==null)Append(hash,Encoding.UTF8.GetBytes("NULL"));
       else{Append(hash,Encoding.UTF8.GetBytes(Encoding.UTF8.GetCharCount(bytes).ToString(CultureInfo.InvariantCulture)+":"));Append(hash,bytes);}
       Append(hash,new byte[]{59});
      }
     }
     if(rc!=101)throw new Exception("Audit statement failed");
    }finally{if(statement!=IntPtr.Zero)sqlite3_finalize(statement);}
   }
   hash.TransformFinalBlock(new byte[0],0,0);return BitConverter.ToString(hash.Hash).Replace("-","");
  }
 }
 public void Dispose(){if(db!=IntPtr.Zero){sqlite3_close_v2(db);db=IntPtr.Zero;}}
}
'@
