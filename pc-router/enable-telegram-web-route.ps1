[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\OracovaVPN-20261003-FA9g4b'
$path = Join-Path $root 'config\cloudflare-named.yml'
$binary = Join-Path $root 'bin\cloudflared.exe'
$before = [IO.File]::ReadAllText($path)
$config = $before | ConvertFrom-Json
$hostname = 'kk.fidior.com'
$pattern = '^/telegram/web(/|$)'
$existing = @($config.ingress | Where-Object { $_.hostname -eq $hostname -and $_.path -eq $pattern })
if ($existing.Count -gt 0) { throw 'Route already exists; inspect instead of overwriting.' }
$request = [Net.HttpWebRequest]::Create('http://127.0.0.1:18180/telegram/web/')
$request.Host = $hostname
$request.Timeout = 5000
try { $response = $request.GetResponse(); $response.Close() }
catch [Net.WebException] {
    if ($null -eq $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 404) { throw 'Private WEB listener is not reachable from Windows' }
    $_.Exception.Response.Close()
}
if (-not $Apply) {
    [pscustomobject]@{ ready=$true; existingRules=@($config.ingress).Count; existingService=(Get-Service OracovaCloudflare).Status.ToString(); proposedService='http://127.0.0.1:18180'; proposedPath=$pattern } | ConvertTo-Json -Compress
    exit
}
$snapshot = Join-Path $root ('telegram-web-route-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $snapshot | Out-Null
$original = Join-Path $snapshot 'cloudflare-named.before.json'
[IO.File]::WriteAllText($original, $before, [Text.UTF8Encoding]::new($false))
$config.ingress = @([pscustomobject]@{hostname=$hostname; path=$pattern; service='http://127.0.0.1:18180'}) + @($config.ingress)
$candidate = Join-Path $root 'config\cloudflare-telegram-web.candidate.json'
if (Test-Path $candidate) { throw 'Candidate file already exists' }
[IO.File]::WriteAllText($candidate, ($config | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
& $binary tunnel --config $candidate ingress validate
if ($LASTEXITCODE -ne 0) { throw 'Cloudflare rejected candidate; active configuration unchanged' }
if ([IO.File]::ReadAllText($path) -cne $before) { throw 'Active tunnel configuration changed during staging' }
[IO.File]::Replace($candidate, $path, (Join-Path $snapshot 'cloudflare-named.replaced.json'))
try {
    Restart-Service OracovaCloudflare
    (Get-Service OracovaCloudflare).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
} catch {
    [IO.File]::WriteAllText($path, $before, [Text.UTF8Encoding]::new($false))
    Start-Service OracovaCloudflare
    throw 'Tunnel restart failed; original configuration restored'
}
[pscustomobject]@{applied=$true; hostname=$hostname; addedPath=$pattern; oldRulesPreserved=$true; rollbackDirectory=$snapshot; service=(Get-Service OracovaCloudflare).Status.ToString()} | ConvertTo-Json -Compress
