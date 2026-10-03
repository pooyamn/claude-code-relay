# Deterministic power policy only. No agent, input simulation, credentials or
# thermal override. System/execution requests prevent idle Modern Standby on AC;
# explicit sleep and firmware thermal safety remain authoritative.
$ErrorActionPreference='Stop'
if(-not [Security.Principal.WindowsIdentity]::GetCurrent().IsSystem){throw 'Protected SYSTEM availability task required'}
Add-Type @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public sealed class NativeRemoteAvailability : IDisposable {
 [StructLayout(LayoutKind.Explicit,Size=32)] struct Reason {
  [FieldOffset(0)] public uint Version;
  [FieldOffset(4)] public uint Flags;
  [FieldOffset(8)] public IntPtr Text;
 }
 [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr PowerCreateRequest(ref Reason reason);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool PowerSetRequest(IntPtr handle,int type);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool PowerClearRequest(IntPtr handle,int type);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
 IntPtr handle; bool system,execution;
 public NativeRemoteAvailability() {
  IntPtr text=Marshal.StringToHGlobalUni("Oracova remote services: remain available when the TV/display is off");
  try { var reason=new Reason{Version=0,Flags=1,Text=text};handle=PowerCreateRequest(ref reason); }
  finally {Marshal.FreeHGlobal(text);}
  if(handle==new IntPtr(-1)||handle==IntPtr.Zero)throw new Win32Exception(Marshal.GetLastWin32Error());
  try {
   if(!PowerSetRequest(handle,1))throw new Win32Exception(Marshal.GetLastWin32Error());system=true;
   if(!PowerSetRequest(handle,3))throw new Win32Exception(Marshal.GetLastWin32Error());execution=true;
  } catch {Dispose();throw;}
 }
 public void Dispose() {
  if(handle==IntPtr.Zero||handle==new IntPtr(-1))return;
  if(execution)PowerClearRequest(handle,3);
  if(system)PowerClearRequest(handle,1);
  CloseHandle(handle);handle=IntPtr.Zero;
 }
}
'@
$request=[NativeRemoteAvailability]::new()
try {while($true){Start-Sleep -Seconds 30}} finally {$request.Dispose()}
