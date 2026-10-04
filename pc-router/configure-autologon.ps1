param([ValidateSet('Inspect','Enable')][string]$Mode='Inspect',[switch]$ReplaceExistingSecret)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Owner-authorized unattended desktop startup. LSA is not protection against
# an administrator or physical access. Never put plaintext passwords in argv/files.
# Explicit replacement retains a DPAPI-encrypted, administrator-only rollback.
# Microsoft documents this Winlogon secret API:
# https://learn.microsoft.com/en-us/windows/win32/secauthn/protecting-the-automatic-logon-password
$ownerSid='S-1-5-21-71459778-1164188569-2276148161-1001'
$root='C:\ProgramData\OracovaNativeRemote'
$key='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator-reviewed configuration required'}
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
public static class OwnerAutologon {
 [StructLayout(LayoutKind.Sequential)] struct Unicode { public ushort Length, MaximumLength; public IntPtr Buffer; }
 [StructLayout(LayoutKind.Sequential)] struct Attributes { public uint Length; public IntPtr Root, Name; public uint Flags; public IntPtr Descriptor, Qos; }
 [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr system, ref Attributes attributes, uint access, out IntPtr handle);
 [DllImport("advapi32.dll")] static extern uint LsaRetrievePrivateData(IntPtr policy, ref Unicode key, out IntPtr data);
 [DllImport("advapi32.dll")] static extern uint LsaStorePrivateData(IntPtr policy, ref Unicode key, IntPtr data);
 [DllImport("advapi32.dll")] static extern uint LsaNtStatusToWinError(uint status);
 [DllImport("advapi32.dll")] static extern uint LsaFreeMemory(IntPtr memory);
 [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr handle);
 [DllImport("advapi32.dll",EntryPoint="LogonUserW",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool LogonUser(string user,string domain,IntPtr password,uint type,uint provider,out IntPtr token);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 static void Check(uint status) { if(status!=0) throw new Win32Exception((int)LsaNtStatusToWinError(status)); }
 static void Zero(IntPtr buffer,int size) { for(int i=0;i<size;i++) Marshal.WriteByte(buffer,i,0); }
 static IntPtr Open(uint access) { var a=new Attributes(); a.Length=(uint)Marshal.SizeOf(a); IntPtr p; Check(LsaOpenPolicy(IntPtr.Zero,ref a,access,out p)); return p; }
 static Unicode Key() { return new Unicode { Length=30, MaximumLength=32, Buffer=Marshal.StringToHGlobalUni("DefaultPassword") }; }
 public static bool Present() {
  IntPtr p=Open(4), data=IntPtr.Zero; var key=Key();
  try { uint status=LsaRetrievePrivateData(p,ref key,out data); if(status==0xC0000034) return false; Check(status); return true; }
  finally { if(data!=IntPtr.Zero) { var value=(Unicode)Marshal.PtrToStructure(data,typeof(Unicode)); if(value.Buffer!=IntPtr.Zero) Zero(value.Buffer,value.Length); LsaFreeMemory(data); } Marshal.FreeHGlobal(key.Buffer); LsaClose(p); }
 }
 public static void ClearCreatedSecret() {
  IntPtr p=Open(0x20); var key=Key();
  try { Check(LsaStorePrivateData(p,ref key,IntPtr.Zero)); } finally { Marshal.FreeHGlobal(key.Buffer); LsaClose(p); }
 }
 public static string ValueFormat() {
  IntPtr p=Open(4), data=IntPtr.Zero;var key=Key();
  try {uint status=LsaRetrievePrivateData(p,ref key,out data);if(status==0xC0000034)return "absent";Check(status);var value=(Unicode)Marshal.PtrToStructure(data,typeof(Unicode));return value.Length>=2&&Marshal.ReadInt16(value.Buffer,value.Length-2)==0?"trailing Unicode terminator":"counted Unicode (no trailing terminator)";}
  finally {if(data!=IntPtr.Zero){var value=(Unicode)Marshal.PtrToStructure(data,typeof(Unicode));if(value.Buffer!=IntPtr.Zero)Zero(value.Buffer,value.Length);LsaFreeMemory(data);}Marshal.FreeHGlobal(key.Buffer);LsaClose(p);}
 }
 static byte[] SealSnapshot(bool present,byte[] value) {
  if(value.Length>65534||value.Length%2!=0||!present&&value.Length!=0)throw new InvalidDataException("Invalid prior credential snapshot");
  var plain=new byte[value.Length+6];plain[0]=79;plain[1]=65;plain[2]=1;plain[3]=(byte)(present?1:0);plain[4]=(byte)value.Length;plain[5]=(byte)(value.Length>>8);Buffer.BlockCopy(value,0,plain,6,value.Length);
  try{return ProtectedData.Protect(plain,Encoding.UTF8.GetBytes("OracovaAutologonRollback/v1"),DataProtectionScope.LocalMachine);}finally{Array.Clear(plain,0,plain.Length);}
 }
 static byte[] OpenSnapshot(byte[] sealedValue) {
  if(sealedValue.Length>131072)throw new InvalidDataException("Credential snapshot exceeds bound");
  var plain=ProtectedData.Unprotect(sealedValue,Encoding.UTF8.GetBytes("OracovaAutologonRollback/v1"),DataProtectionScope.LocalMachine);
  if(plain.Length<6||plain.Length>65540||plain[0]!=79||plain[1]!=65||plain[2]!=1||plain[3]>1||
   plain.Length!=6+(plain[4]|plain[5]<<8)||(plain.Length-6)%2!=0||plain[3]==0&&plain.Length!=6){Array.Clear(plain,0,plain.Length);throw new InvalidDataException("Invalid encrypted credential snapshot");}
  return plain;
 }
 static void BackupPrevious(IntPtr previous,string path) {
  byte[] value=null,sealedValue=null;
  try {
   var old=previous==IntPtr.Zero?new Unicode():(Unicode)Marshal.PtrToStructure(previous,typeof(Unicode));value=new byte[old.Length];
   if(value.Length!=0)Marshal.Copy(old.Buffer,value,0,value.Length);sealedValue=SealSnapshot(previous!=IntPtr.Zero,value);
   using(var file=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.None)){file.Write(sealedValue,0,sealedValue.Length);file.Flush(true);}
  }finally{if(value!=null)Array.Clear(value,0,value.Length);if(sealedValue!=null)Array.Clear(sealedValue,0,sealedValue.Length);}
 }
 public static void RestoreSnapshot(string path) {
  byte[] plain=null;IntPtr p=IntPtr.Zero,buffer=IntPtr.Zero,data=IntPtr.Zero;var key=Key();
  try {
   var file=new FileInfo(path);if(file.Length>131072)throw new InvalidDataException("Credential rollback exceeds bound");plain=OpenSnapshot(File.ReadAllBytes(path));p=Open(0x20);
   if(plain[3]==0){Check(LsaStorePrivateData(p,ref key,IntPtr.Zero));return;}
   int length=plain.Length-6;buffer=Marshal.AllocHGlobal(length+2);Zero(buffer,length+2);Marshal.Copy(plain,6,buffer,length);
   var value=new Unicode {Length=(ushort)length,MaximumLength=(ushort)Math.Min(length+2,65535),Buffer=buffer};data=Marshal.AllocHGlobal(Marshal.SizeOf(value));Marshal.StructureToPtr(value,data,false);Check(LsaStorePrivateData(p,ref key,data));
  }finally{if(buffer!=IntPtr.Zero){Zero(buffer,plain.Length-4);Marshal.FreeHGlobal(buffer);}if(data!=IntPtr.Zero)Marshal.FreeHGlobal(data);if(plain!=null)Array.Clear(plain,0,plain.Length);Marshal.FreeHGlobal(key.Buffer);if(p!=IntPtr.Zero)LsaClose(p);}
 }
 public static bool StoreFromPrivateInput(string expectedSid,bool replaceExisting,string snapshot) {
  IntPtr password=Marshal.AllocHGlobal(1024), token=IntPtr.Zero, p=IntPtr.Zero, data=IntPtr.Zero, previous=IntPtr.Zero; var key=Key(); Zero(password,1024);
  try {
   int length=0;
   while(true) { int c=Console.In.Read(); if(c<0) throw new InvalidOperationException("Private password input ended before newline"); if(c==10) break; if(c==13) continue; if(c==0||length>=255) throw new InvalidOperationException("Invalid private password input"); Marshal.WriteInt16(password,length++*2,(short)c); }
   if(length==0) throw new InvalidOperationException("Empty password refused");
   if(!LogonUser("pou",".",password,2,0,out token)) throw new Win32Exception(Marshal.GetLastWin32Error(),"Owner interactive credentials failed validation");
   using(var identity=new WindowsIdentity(token)) { if(identity.User.Value!=expectedSid) throw new InvalidOperationException("Unexpected credential identity"); }
   p=Open(0x24);
   uint status=LsaRetrievePrivateData(p,ref key,out previous);
   if(status==0) {
    var old=(Unicode)Marshal.PtrToStructure(previous,typeof(Unicode)); int effectiveLength=old.Length;
    // Some writers include a trailing UTF-16 NUL in Length. Winlogon treats
    // that terminator as encoding, not as an extra password character.
    while(effectiveLength>=2&&Marshal.ReadInt16(old.Buffer,effectiveLength-2)==0)effectiveLength-=2;
    int difference=effectiveLength^(length*2);
    for(int i=0;i<length;i++) difference|=Marshal.ReadInt16(password,i*2)^(i*2<effectiveLength?Marshal.ReadInt16(old.Buffer,i*2):0);
    if(difference==0)return false; // Validated existing owner secret reused without mutation.
    if(!replaceExisting)throw new InvalidOperationException("Existing LSA credential differs; preserved, autologon not enabled");
   }
   if(status!=0&&status!=0xC0000034)Check(status);
   BackupPrevious(previous,snapshot); // Durable encrypted preimage before the only secret write.
   var value=new Unicode { Length=(ushort)(length*2), MaximumLength=(ushort)(length*2+2), Buffer=password };
   data=Marshal.AllocHGlobal(Marshal.SizeOf(value)); Marshal.StructureToPtr(value,data,false); Check(LsaStorePrivateData(p,ref key,data));return true;
  } finally { if(previous!=IntPtr.Zero){var old=(Unicode)Marshal.PtrToStructure(previous,typeof(Unicode));if(old.Buffer!=IntPtr.Zero)Zero(old.Buffer,old.Length);LsaFreeMemory(previous);} Zero(password,1024); Marshal.FreeHGlobal(password); Marshal.FreeHGlobal(key.Buffer); if(data!=IntPtr.Zero) Marshal.FreeHGlobal(data); if(p!=IntPtr.Zero) LsaClose(p); if(token!=IntPtr.Zero) CloseHandle(token); }
 }
}
'@ -ReferencedAssemblies @('System','System.Security')
$account=Get-LocalUser -Name pou
$computer=Get-CimInstance Win32_ComputerSystem
$winlogon=Get-ItemProperty $key
$secretPresent=[OwnerAutologon]::Present()
$plaintextPresent=$null -ne (Get-Item $key).GetValue('DefaultPassword',$null)
if($Mode -eq 'Inspect'){
 [Console]::WriteLine(([ordered]@{ownerSid=$account.SID.Value;autoAdminLogon=$winlogon.AutoAdminLogon;lsaSecretPresent=$secretPresent;lsaValueFormat=[OwnerAutologon]::ValueFormat();plaintextPasswordPresent=$plaintextPresent;domainJoined=$computer.PartOfDomain} | ConvertTo-Json -Compress)); exit 0
}
if($account.SID.Value -ne $ownerSid -or -not $account.Enabled -or $computer.PartOfDomain){throw 'Unexpected local owner/account/domain'}
if($plaintextPresent -or $winlogon.AutoAdminLogon -ne '0' -or $winlogon.DefaultUserName -ne 'pou' -or $null -ne (Get-Item $key).GetValue('AutoLogonCount',$null)){throw 'Unexpected autologon override state: inspect and merge; do not overwrite credentials'}
if($account.PasswordExpires){throw 'Expiring password would break unattended recovery'}
$policy=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
foreach($name in @('legalnoticetext','legalnoticecaption')){if(([string]$policy.$name).Trim([char]0).Length){throw 'Interactive legal notice prevents unattended sign-in; policy preserved'}}
if(-not (Test-Path $root) -or ((Get-Item $root).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Protected installation required'}
$snapshot=Join-Path $root ('autologon-before-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $snapshot | Out-Null
$acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetAccessRuleProtection($true,$false)
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$acl.SetOwner($admin)
foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))}
Set-Acl $snapshot $acl
$before=@()
foreach($name in @('DefaultUserName','DefaultDomainName','AutoAdminLogon')){
 $registry=Get-Item $key;$present=$registry.GetValueNames() -contains $name
 $before+=@{name=$name;present=$present;value=$registry.GetValue($name,$null);kind=$(if($present){$registry.GetValueKind($name).ToString()}else{$null})}
}
[IO.File]::WriteAllText((Join-Path $snapshot 'registry.json'),($before|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
$stored=$false
$secretSnapshot=Join-Path $snapshot 'prior-secret.dpapi'
try {
 [Console]::WriteLine('PRIVATE-INPUT-READY');[Console]::Out.Flush()
 $stored=[OwnerAutologon]::StoreFromPrivateInput($ownerSid,[bool]$ReplaceExistingSecret,$secretSnapshot)
 New-ItemProperty $key DefaultUserName -Value 'pou' -PropertyType String -Force | Out-Null
 New-ItemProperty $key DefaultDomainName -Value $env:COMPUTERNAME -PropertyType String -Force | Out-Null
 # Enable last, only after password and owner validation.
 New-ItemProperty $key AutoAdminLogon -Value '1' -PropertyType String -Force | Out-Null
 if(-not [OwnerAutologon]::Present() -or (Get-ItemProperty $key).AutoAdminLogon -ne '1' -or $null -ne (Get-Item $key).GetValue('DefaultPassword',$null)){throw 'Autologon readback failed'}
 [Console]::WriteLine(([ordered]@{configured=$true;credentialSidVerified=$ownerSid;passwordStore='LSA private data; no plaintext registry value';existingSecretReused=(-not $stored);existingSecretReplaced=($stored -and $secretPresent);encryptedRollbackPresent=(Test-Path $secretSnapshot);snapshot=$snapshot;rebootVerified=$false} | ConvertTo-Json -Compress))
} catch {
 # Restore the exact prior secret (including absence) and three changed values.
 try {foreach($entry in $before){if($entry.present){New-ItemProperty $key $entry.name -Value $entry.value -PropertyType $entry.kind -Force | Out-Null}else{Remove-ItemProperty $key $entry.name -ErrorAction SilentlyContinue}}}
 finally {if(Test-Path $secretSnapshot){[OwnerAutologon]::RestoreSnapshot($secretSnapshot)}}
 throw
}
