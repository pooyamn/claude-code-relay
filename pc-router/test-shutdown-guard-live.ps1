# Simulated query messages only. Never calls ExitWindows/shutdown/restart.
$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class ShutdownGuardCheck {
 public delegate bool Callback(IntPtr h,IntPtr p);
 [DllImport("user32.dll")] static extern bool EnumWindows(Callback f,IntPtr p);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h,StringBuilder b,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern bool ShutdownBlockReasonQuery(IntPtr h,StringBuilder b,ref uint n);
 [DllImport("user32.dll",SetLastError=true)] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,uint f,uint t,out UIntPtr r);
 public static IntPtr Window() {
  IntPtr found=IntPtr.Zero;
  EnumWindows(delegate(IntPtr h,IntPtr p){var b=new StringBuilder(256);GetWindowText(h,b,256);
   if(b.ToString()=="Oracova remote PC shutdown guard")found=h;return true;},IntPtr.Zero);
  return found;
 }
}
'@
$window=[ShutdownGuardCheck]::Window()
if($window -eq [IntPtr]::Zero){throw 'Guard window missing'}
$b=[Text.StringBuilder]::new(512);[uint32]$n=512
$reason=[ShutdownGuardCheck]::ShutdownBlockReasonQuery($window,$b,[ref]$n)
[UIntPtr]$r=[UIntPtr]::Zero
$ok=[ShutdownGuardCheck]::SendMessageTimeout($window,17,[IntPtr]::Zero,[IntPtr]::Zero,3,2000,[ref]$r)
$veto=$ok -ne [IntPtr]::Zero -and $r.ToUInt64() -eq 0
$ok=[ShutdownGuardCheck]::SendMessageTimeout($window,17,[IntPtr]::Zero,[IntPtr]1073741824,3,2000,[ref]$r)
$critical=$ok -ne [IntPtr]::Zero -and $r.ToUInt64() -eq 1
if(-not $reason -or -not $veto -or -not $critical){throw 'Live guard acceptance failed'}
[pscustomobject]@{reasonRegistered=$reason;ordinaryShutdownVeto=$veto;criticalNotBlocked=$critical;realShutdownRequested=$false}|ConvertTo-Json -Compress
