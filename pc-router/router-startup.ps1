$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Deterministic SYSTEM lifecycle only. No prompts, model actions, credential
# readout or agent restart. The service itself still enforces the owner token.
$root='C:\ProgramData\KhadangRouter'
$ownerSid='S-1-5-21-71459778-1164188569-2276148161-1001'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not $identity.IsSystem -or [Diagnostics.Process]::GetCurrentProcess().SessionId -ne 0){throw 'SYSTEM session-zero startup supervisor required'}
$service=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
$expected='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
if(-not $service -or $service.StartName -ne 'LocalSystem' -or $service.PathName -ne $expected -or $service.StartMode -ne 'Manual'){throw 'Unexpected service configuration; refuse startup'}
if($service.State -eq 'Running'){[Console]::WriteLine('Already running; no effect');exit 0}
if($service.State -ne 'Stopped'){[Console]::WriteLine('SCM transition in progress; no effect');exit 0}
$probe=Get-Content "$root\state\probe.json" -Raw | ConvertFrom-Json
if(-not $probe.verified -or -not $probe.credentialAndCodeDenied -or -not $probe.aclProbeWithoutProviderSandbox -or $probe.nativeOwnerSid -ne $ownerSid){throw 'Matching owner/credential isolation probe required'}
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $probe.routerSha256 -or (Get-FileHash "$root\config.json").Hash -ne $probe.policySha256){throw 'Reviewed router/policy changed; re-probe before startup'}
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
public static class ConsoleOwnerReady {
 [StructLayout(LayoutKind.Sequential)] struct Luid { public uint Low; public int High; }
 [StructLayout(LayoutKind.Sequential)] struct Privileges { public uint Count; public Luid Luid; public uint Flags; }
 [DllImport("kernel32.dll")] static extern uint WTSGetActiveConsoleSessionId();
 [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 [DllImport("wtsapi32.dll",SetLastError=true)] static extern bool WTSQueryUserToken(uint session,out IntPtr token);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
 [DllImport("advapi32.dll",EntryPoint="LookupPrivilegeValueW",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool LookupPrivilegeValue(string system,string name,out Luid luid);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool AdjustTokenPrivileges(IntPtr token,bool disable,ref Privileges privileges,uint size,IntPtr previous,IntPtr needed);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool GetTokenInformation(IntPtr token,int info,out int value,uint size,out uint needed);
 public static bool Ready(string expectedSid) {
  uint session=WTSGetActiveConsoleSessionId();if(session==0||session==uint.MaxValue)return false;
  IntPtr token=IntPtr.Zero, current=IntPtr.Zero;
  try {
   if(!OpenProcessToken(GetCurrentProcess(),0x28,out current))throw new Win32Exception(Marshal.GetLastWin32Error());
   var p=new Privileges { Count=1,Flags=2 };if(!LookupPrivilegeValue(null,"SeTcbPrivilege",out p.Luid)||!AdjustTokenPrivileges(current,false,ref p,0,IntPtr.Zero,IntPtr.Zero)||Marshal.GetLastWin32Error()!=0)throw new Win32Exception(Marshal.GetLastWin32Error());
   if(!WTSQueryUserToken(session,out token)){if(Marshal.GetLastWin32Error()==1008)return false;throw new Win32Exception(Marshal.GetLastWin32Error());}
   using(var identity=new WindowsIdentity(token)){if(identity.IsSystem||identity.User.Value!=expectedSid)return false;}
   int elevated;uint needed;if(!GetTokenInformation(token,20,out elevated,4,out needed))throw new Win32Exception(Marshal.GetLastWin32Error());return elevated==0;
  } finally {if(token!=IntPtr.Zero)CloseHandle(token);if(current!=IntPtr.Zero)CloseHandle(current);}
 }
}
'@
if(-not [ConsoleOwnerReady]::Ready($ownerSid)){[Console]::WriteLine('Waiting for exact non-elevated console owner; no agent started');exit 0}
Start-Service KhadangRouter
[Console]::WriteLine('Owner ready; SCM startup requested. Interrupted turns remain held by the router ledger.')
