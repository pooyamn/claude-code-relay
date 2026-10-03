param([Parameter(Mandatory=$true)][ValidateSet('Codex','Claude')][string]$Provider)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$ownerSid = 'S-1-5-21-71459778-1164188569-2276148161-1001'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$state = 'C:\Users\pou\.native-remote'
$resultPath = Join-Path $state ($Provider.ToLowerInvariant()+'-status.json')
$utf8 = [Text.UTF8Encoding]::new($false)
$actuallyElevated = $null
function Save-State($stateName,$details) {
    $result = [ordered]@{provider=$Provider;state=$stateName;host=$env:COMPUTERNAME;ownerSid=$identity.User.Value;
        elevated=$actuallyElevated;sessionId=[Diagnostics.Process]::GetCurrentProcess().SessionId;pid=$PID;at=[DateTime]::UtcNow.ToString('o');details=$details}
    [IO.File]::WriteAllText($resultPath,($result | ConvertTo-Json -Depth 8),$utf8)
}
function Read-ClaudeRemoteStatus([string]$text) {
    $plain=[regex]::Replace($text,'\x1b\[[0-?]*[ -/]*[@-~]','')
    $matches=[regex]::Matches($plain,'(?im)(?:^|[\u00b7\u2022])\s*(Connected|Connecting|Disconnected|Reconnecting)\s*[\u00b7\u2022]')
    if($matches.Count){return $matches[$matches.Count-1].Groups[1].Value.ToLowerInvariant()}
    return $null
}
try {
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NativeRemoteToken {
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool GetTokenInformation(IntPtr token,int informationClass,out int value,int size,out int returned);
 public static bool Elevated(IntPtr token) { int value,returned; if(!GetTokenInformation(token,20,out value,4,out returned))throw new Exception("Token verification failed");return value!=0; }
}
'@
$actuallyElevated = [NativeRemoteToken]::Elevated($identity.Token)
if ($identity.User.Value -ne $ownerSid -or $identity.IsSystem -or $actuallyElevated) {
    throw 'Remote agents require the exact non-elevated owner, never SSH administrator or SYSTEM'
}
if (-not (Test-Path $state)) { throw 'Reviewed owner-private runtime directory required' }
    if ($Provider -eq 'Codex') {
        Set-Location 'C:\Users\pou\workspaces'
        $exe = 'C:\Users\pou\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe'
        # WORKAROUND for characterized native Windows 0.160.0 launch defects:
        # Task Scheduler denies detached-child breakaway; remote-control's
        # foreground temp directory fails its own private-socket ACL check.
        # Supervise the same native app-server over private stdio and enable
        # its supported remoteControl protocol. No public socket or model turn.
        $arguments = 'app-server --stdio'
    }
    else {
        Set-Location 'C:\Users\pou\workspaces\pc-control'
        Save-State 'starting' @{workspace=(Get-Location).Path}
        $exe = 'C:\Users\pou\.local\bin\claude.exe'
        # Native server restores its own saved sessions for this directory.
        # No -p, automatic task prompt, new-session fallback or API key.
        $arguments = 'remote-control --name "PC - Native Claude" --spawn worktree --capacity 3 --permission-mode bypassPermissions'
    }
    $info = [Diagnostics.ProcessStartInfo]::new($exe,$arguments)
    $info.UseShellExecute=$false;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $info.RedirectStandardInput=$true
    $info.WorkingDirectory=(Get-Location).Path;$info.CreateNoWindow=$true
    $stem=$Provider.ToLowerInvariant()
    $stdout = [IO.FileStream]::new((Join-Path $state ($stem+'-server-private.txt')),[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::Read,1)
    $stderr = [IO.FileStream]::new((Join-Path $state ($stem+'-stderr-private.txt')),[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::Read,1)
    try {
        $process = [Diagnostics.Process]::Start($info)
        $errTask=$process.StandardError.BaseStream.CopyToAsync($stderr)
        $details=@{workspace=(Get-Location).Path;nativePid=$process.Id;onlineVerified=$false}
        Save-State 'native-process-running' $details
        if($Provider -eq 'Codex') {
            $writer=[IO.StreamWriter]::new($stdout,$utf8,1024,$true);$writer.AutoFlush=$true
            $process.StandardInput.WriteLine('{"id":1,"method":"initialize","params":{"clientInfo":{"name":"oracova_native_remote","version":"1"},"capabilities":{"experimentalApi":true}}}')
            $nextLine=$process.StandardOutput.ReadLineAsync()
            while(-not $process.HasExited) {
                if(-not $nextLine.IsCompleted){$process.WaitForExit(250) | Out-Null;continue}
                $line=$nextLine.GetAwaiter().GetResult()
                if($null -eq $line){break}
                $writer.WriteLine($line)
                $message=$line | ConvertFrom-Json
                # Server requests can also carry IDs. Never interpret an
                # approval/input request as one of our initialization replies.
                $isReply=$message.PSObject.Properties['id'] -and -not $message.PSObject.Properties['method']
                if($isReply -and $message.id -eq 1) {
                    if($message.PSObject.Properties['error']){throw 'Native protocol initialization rejected'}
                    $process.StandardInput.WriteLine('{"method":"initialized"}')
                    $process.StandardInput.WriteLine('{"id":2,"method":"remoteControl/enable","params":{"ephemeral":false}}')
                }
                $remote=$null
                if($isReply -and $message.id -eq 2) {
                    if($message.PSObject.Properties['error']){throw 'Native remoteControl/enable rejected'}
                    $remote=$message.result
                } elseif($message.PSObject.Properties['method'] -and $message.method -eq 'remoteControl/status/changed') {$remote=$message.params}
                if($remote) {
                    $details.remoteStatus=$remote.status
                    $details.onlineVerified=($remote.status -eq 'connected')
                    $details.serverName=$remote.serverName
                    Save-State 'native-process-running' $details
                }
                $nextLine=$process.StandardOutput.ReadLineAsync()
            }
            $writer.Dispose()
        } else {
            $outTask=$process.StandardOutput.BaseStream.CopyToAsync($stdout)
            $consentSent=$false
            while(-not $process.WaitForExit(1000)) {
                # Answer ONLY the exact native first-use consent requested by
                # the owner; never feed y to task/agent permission prompts.
                    $read=[IO.FileStream]::new((Join-Path $state 'claude-server-private.txt'),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
                    if($read.Length -gt 8192){$read.Seek(-8192,[IO.SeekOrigin]::End) | Out-Null}
                    $reader=[IO.StreamReader]::new($read)
                    try {$text=$reader.ReadToEnd()} finally {$reader.Dispose()}
                    if(-not $consentSent -and $text.Contains('Enable Remote Control? (y/n)')) {
                        $process.StandardInput.WriteLine('y');$process.StandardInput.Flush()
                        $consentSent=$true;$details.nativeConsentAccepted=$true
                        Save-State 'native-process-running' $details
                    }
                    $observed=Read-ClaudeRemoteStatus $text
                    if($observed -and $observed -ne $details.remoteStatus){
                        $details.remoteStatus=$observed;$details.onlineVerified=($observed -eq 'connected')
                        Save-State 'native-process-running' $details
                    }
            }
            $outTask.GetAwaiter().GetResult()
        }
        $process.WaitForExit();$errTask.GetAwaiter().GetResult()
        $code = $process.ExitCode
    } finally {$stdout.Dispose();$stderr.Dispose();if($process){$process.Dispose()}}
    Save-State 'exited' @{exitCode=$code}
    exit $code
}
catch {
    Save-State 'failed' @{errorType=$_.Exception.GetType().Name;message=$_.Exception.Message}
    exit 1
}
