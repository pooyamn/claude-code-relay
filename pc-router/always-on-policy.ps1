param([ValidateSet('Inspect','Apply','Guard')][string]$Mode='Inspect')
# Ordinary OS power policy only. Do not disable ACPI/thermal drivers or safety,
# force-abort shutdowns, change firmware, or restart any native agent.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Reviewed PC administrator required'
}
if($Mode -eq 'Guard' -and -not $identity.IsSystem){throw 'SYSTEM policy guard required'}
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AlwaysOnPowerRead {
 [DllImport("powrprof.dll")] static extern uint PowerReadACValueIndex(IntPtr root,ref Guid scheme,ref Guid group,ref Guid setting,out uint value);
 [DllImport("powrprof.dll")] static extern uint PowerReadDCValueIndex(IntPtr root,ref Guid scheme,ref Guid group,ref Guid setting,out uint value);
 public static uint Read(Guid scheme,Guid group,Guid setting,bool ac) {
  uint v; uint code=ac ? PowerReadACValueIndex(IntPtr.Zero,ref scheme,ref group,ref setting,out v) : PowerReadDCValueIndex(IntPtr.Zero,ref scheme,ref group,ref setting,out v);
  if(code!=0)throw new InvalidOperationException("Power setting read failed");return v;
 }
}
'@
$native='C:\Windows\System32\powercfg.exe'
$schemeText=(& $native /getactivescheme) -join ' '
if($LASTEXITCODE -ne 0 -or $schemeText -notmatch '[0-9a-fA-F-]{36}'){throw 'Active power plan required'}
$scheme=[Guid]$Matches[0]
$sleep='238c9fa8-0aad-41ed-83f4-97be242c8f20';$buttons='4f971e89-eebd-4455-a8de-9e59040e7347'
$settings=@(
 @($sleep,'29f6c1db-86da-48c5-9fdb-f2b67b1f44da','sleep-timeout'),
 @($sleep,'9d7815a6-7ee4-497e-8888-515a05f02364','hibernate-timeout'),
 @($sleep,'94ac6d29-73ce-41a6-809f-6363ba21b47e','hybrid-sleep'),
 @($sleep,'7bc4a2f9-d8fc-4469-b07b-33eb785aaca0','unattended-sleep'),
 @($sleep,'abfc2519-3608-4c2a-94ea-171b0ed546ab','allow-standby'),
 @($buttons,'7648efa3-dd9c-4e3e-b566-50f929386280','power-button'),
 @($buttons,'96996bc0-ad50-47ec-923b-6f41874dd9eb','sleep-button'),
 @($buttons,'5ca83367-6e45-459f-a27b-476b1d01c936','lid-action')
)
$before=@(foreach($s in $settings){
 [pscustomobject]@{name=$s[2];group=$s[0];setting=$s[1];ac=[AlwaysOnPowerRead]::Read($scheme,$s[0],$s[1],$true);dc=[AlwaysOnPowerRead]::Read($scheme,$s[0],$s[1],$false)}
})
$au='HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
$fast='HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power'
$oldAU=Get-ItemProperty -LiteralPath $au -ErrorAction SilentlyContinue
$oldFast=Get-ItemProperty -LiteralPath $fast -ErrorAction SilentlyContinue
$hibernation=Test-Path -LiteralPath 'C:\hiberfil.sys'
$snapshot=[pscustomobject]@{at=[DateTime]::UtcNow.ToString('o');scheme=$scheme.ToString();settings=$before;
 hibernationFile=$hibernation;NoAutoUpdate=$oldAU.NoAutoUpdate;NoAutoRebootWithLoggedOnUsers=$oldAU.NoAutoRebootWithLoggedOnUsers;HiberbootEnabled=$oldFast.HiberbootEnabled}
if($Mode -eq 'Inspect'){$snapshot|ConvertTo-Json -Depth 5 -Compress;return}
if($Mode -eq 'Apply'){
 # Protected generation supplied by the installer; never overwrite preimages.
 $snapshot|ConvertTo-Json -Depth 5|Out-File -LiteralPath (Join-Path $PSScriptRoot 'power-before.json') -Encoding UTF8 -NoClobber
 (& $native /a)|Set-Content (Join-Path $PSScriptRoot 'power-capabilities-before.txt') -Encoding UTF8
}
$changed=$false
foreach($s in $before){
 foreach($kind in @('ac','dc')){
  if($s.$kind -ne 0){
   $verb=if($kind -eq 'ac'){'/setacvalueindex'}else{'/setdcvalueindex'}
   $null=& $native $verb $scheme $s.group $s.setting 0
   if($LASTEXITCODE -ne 0){throw 'Power setting apply failed'}
   $changed=$true
  }
 }
}
if($hibernation -or $Mode -in @('Apply','Guard')){
 $null=& $native /hibernate off
 if($LASTEXITCODE -ne 0){throw 'Hibernation disable failed'}
 if($hibernation -or $Mode -eq 'Apply'){$changed=$true}
}
if($oldFast.HiberbootEnabled -ne 0){
 New-ItemProperty -LiteralPath $fast -Name HiberbootEnabled -Value 0 -PropertyType DWord -Force|Out-Null;$changed=$true
}
if(-not (Test-Path $au)){New-Item -Path $au -Force|Out-Null}
foreach($name in @('NoAutoUpdate','NoAutoRebootWithLoggedOnUsers')){
 if($oldAU.$name -ne 1){New-ItemProperty -LiteralPath $au -Name $name -Value 1 -PropertyType DWord -Force|Out-Null;$changed=$true}
}
if($changed){$null=& $native /setactive $scheme;if($LASTEXITCODE -ne 0){throw 'Power plan activation failed'}}
foreach($s in $settings){
 if([AlwaysOnPowerRead]::Read($scheme,$s[0],$s[1],$true) -ne 0 -or [AlwaysOnPowerRead]::Read($scheme,$s[0],$s[1],$false) -ne 0){throw 'Power setting readback failed'}
}
if(Test-Path 'C:\hiberfil.sys'){throw 'Hibernation file still present'}
$receipt=[pscustomobject]@{at=[DateTime]::UtcNow.ToString('o');changed=$changed;standbyAllowed=$false;hibernation=$false;
 automaticUpdatesDisabled=$true;manualUpdatesAvailable=$true;hardwareSafetyUnchanged=$true;physicalPowerLossPrevented=$false}
$receipt|ConvertTo-Json -Compress|Set-Content -LiteralPath (Join-Path $PSScriptRoot 'power-status.json') -Encoding UTF8
$receipt|ConvertTo-Json -Compress
