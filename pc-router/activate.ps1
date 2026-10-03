param([ValidateSet('canary','live')][string]$Mode = 'canary')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = 'C:\ProgramData\KhadangRouter'
$service = Get-CimInstance Win32_Service | Where-Object Name -eq 'KhadangRouter'
if (-not $service -or $service.StartName -ne 'LocalSystem' -or -not $service.PathName.StartsWith('"'+$root+'\bin\KhadangRouter.exe" ')) { throw 'Unexpected existing service' }
$proof = Get-Content "$root\state\probe.json" -Raw | ConvertFrom-Json
if (-not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or
    $proof.policySha256 -ne (Get-FileHash "$root\config.json" -Algorithm SHA256).Hash -or
    $proof.routerSha256 -ne (Get-FileHash "$root\bin\KhadangRouter.dll" -Algorithm SHA256).Hash) { throw 'Matching OS-boundary probe required' }
Stop-Service KhadangRouter
(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
$argument = if ($Mode -eq 'canary') {'--canary-service'} else {'--service'}
$command = '"'+$root+'\bin\KhadangRouter.exe" '+$argument+' --config "'+$root+'\config.json"'
$changed = Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{PathName=$command;StartMode='Manual'}
if ($changed.ReturnValue -ne 0) { throw 'SCM configuration failed' }
Start-Service KhadangRouter
[PSCustomObject]@{service=(Get-Service KhadangRouter).Status.ToString();mode=$Mode;polling='Starting on PC only';host=$env:COMPUTERNAME} | ConvertTo-Json -Compress
