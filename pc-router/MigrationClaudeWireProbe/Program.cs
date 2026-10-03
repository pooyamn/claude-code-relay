using System.Diagnostics;
using System.Security.Principal;
using System.Text.Json;
using KhadangRouter;

// One fresh tools-disabled subscription prompt through the real typed client.
// No project resume, Telegram polling, remote enrollment or production change.
const string prompt = "Reply exactly MIGRATION_CLAUDE_WIRE_OK. Do not use any tools.";
string? state = null;
DiagnosticChannel? channel = null;
var report = new Dictionary<string, object?> { ["complete"] = false, ["routingChanged"] = false,
    ["existingConversationsResumed"] = false, ["activeTurnSteeringVerified"] = false, ["phoneRoundTripVerified"] = false };
try
{
    if (!OperatingSystem.IsWindows() || args.Length != 2 || args[0] != "--run" || !Guid.TryParseExact(args[1], "N", out var run))
        throw new InvalidDataException("Exact Windows migration diagnostic required");
    using var identity = WindowsIdentity.GetCurrent();
    if (Environment.MachineName != "DESKTOP-8SO9HDK" || identity.User?.Value != "S-1-5-21-71459778-1164188569-2276148161-1001" ||
        identity.IsSystem || new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator) || Process.GetCurrentProcess().SessionId != 1)
        throw new InvalidDataException("Exact Interactive/Limited ordinary owner in session 1 required");
    report["ownerSid"] = identity.User.Value; report["session"] = 1; report["elevated"] = false;
    var denied = false;
    try { using var file = File.OpenRead(@"C:\ProgramData\KhadangRouter\khadang-token.dpapi"); }
    catch (UnauthorizedAccessException) { denied = true; }
    if (!denied) throw new InvalidDataException("Actual protected bot credential denial required");
    report["windowsCredentialReadDenied"] = true;
    state = @"C:\Users\pou\.native-remote\migration-claude-wire-" + run.ToString("N");
    if (Directory.Exists(state) || File.Exists(state)) throw new InvalidDataException("Prior attempt preserved; never replay");
    Directory.CreateDirectory(state);
    using var claim = new FileStream(Path.Combine(state, "one-shot.claim"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
    using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(75));
    var script = "/mnt/c/ProgramData/OracovaNativeRemote/migration-claude-wire-" + run.ToString("N") + "/check-pc-claude-wire.py";
    channel = await DiagnosticChannel.Start(script, run.ToString("N"), state, stop.Token);
    var session = channel.Ready.GetProperty("session_id").GetString()!;
    report["nativeSessionId"] = session; report["linuxUid"] = 1000;
    report["nativePid"] = channel.Ready.GetProperty("native_pid").GetInt32();
    report["linuxCredentialReadDenied"] = true;
    using var ledger = new Ledger(Path.Combine(state, "wire.db"));
    await using (var client = new ClaudeNativeStream(channel, ledger, session))
    {
        var result = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        var idle = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var completedResult = 0;
        var partials = 0;
        client.Notification += message => {
            var kind = message.GetProperty("type").GetString();
            if (kind == "stream_event") Interlocked.Increment(ref partials);
            if (kind == "result") { Volatile.Write(ref completedResult, 1); result.TrySetResult(message); }
            if (kind == "system" && message.TryGetProperty("subtype", out var subtype) && subtype.GetString() == "session_state_changed" &&
                message.GetProperty("state").GetString() == "idle" && Volatile.Read(ref completedResult) == 1) idle.TrySetResult();
        };
        var initialized = await client.Initialize(stop.Token);
        if (initialized.GetProperty("session_state").GetString() != "idle") throw new InvalidDataException("Fresh Claude diagnostic must initialize idle");
        report["initialized"] = true;
        var receipt = await client.SendNow(session, JsonSerializer.SerializeToElement(prompt), stop.Token);
        report["nativeInputReceipt"] = receipt.GetProperty("uuid").GetString();
        report["nativeInputConsumed"] = true;
        var response = await result.Task.WaitAsync(stop.Token);
        if (response.GetProperty("session_id").GetString() != session || response.GetProperty("subtype").GetString() != "success" ||
            response.GetProperty("is_error").GetBoolean() || response.GetProperty("result").GetString()!.Trim() != "MIGRATION_CLAUDE_WIRE_OK")
            throw new InvalidDataException("Native result is not the exact fresh diagnostic reply");
        await idle.Task.WaitAsync(stop.Token);
        if (ledger.Unknown != 0) throw new InvalidDataException("Diagnostic has an uncertain delivery; never replay");
        report["exactModelReply"] = true; report["nativeIdleAfterResult"] = true;
        report["partialEvents"] = partials; report["unknownEffects"] = 0;
    }
    report["complete"] = channel.Exited && channel.ExitCode == 0;
    if (!(bool)report["complete"]!) throw new InvalidDataException("Owned native bridge did not exit cleanly");
}
catch (Exception error)
{
    report["complete"] = false; report["failureType"] = error.GetType().Name;
    if (state != null) File.WriteAllText(Path.Combine(state, "failure.private.txt"), error.ToString());
    Environment.ExitCode = 1;
}
finally
{
    if (channel != null) await channel.DisposeAsync();
    report["windowsLauncherStopped"] = channel?.Exited ?? true;
    report["at"] = DateTimeOffset.UtcNow;
    if (state != null) File.WriteAllText(Path.Combine(state, "result.json"), JsonSerializer.Serialize(report));
    Console.WriteLine(JsonSerializer.Serialize(report));
}

sealed class DiagnosticChannel(Process child, string state) : INativeChannel
{
    private readonly Task<string> error = child.StandardError.ReadToEndAsync();
    private bool disposed;
    public JsonElement Ready { get; private set; }
    public uint Pid => checked((uint)child.Id); // Windows launcher observation only.
    public bool Exited => child.HasExited;
    public int ExitCode => child.ExitCode;
    public static async Task<DiagnosticChannel> Start(string script, string run, string state, CancellationToken stop)
    {
        var launch = new ProcessStartInfo(@"C:\Windows\System32\wsl.exe") { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in new[] { "-d", "Ubuntu-24.04", "-u", "pou", "--exec", "/usr/bin/python3", "-I", "-B", script, "--run", run }) launch.ArgumentList.Add(argument);
        var process = Process.Start(launch) ?? throw new IOException("Owned diagnostic bridge did not start");
        var channel = new DiagnosticChannel(process, state);
        try
        {
            var line = await channel.Read(stop) ?? throw new IOException("Native diagnostic ended before ready");
            using var document = JsonDocument.Parse(line);
            channel.Ready = document.RootElement.Clone();
            if (channel.Ready.GetProperty("type").GetString() != "migration_claude_ready" ||
                channel.Ready.GetProperty("uid").GetInt32() != 1000 || channel.Ready.GetProperty("native_uid").GetInt32() != 1000 ||
                !channel.Ready.GetProperty("credential_read_denied").GetBoolean() ||
                !Guid.TryParseExact(channel.Ready.GetProperty("session_id").GetString(), "D", out _))
                throw new InvalidDataException("Native pinned owner/credential/session evidence missing");
            return channel;
        }
        catch { await channel.DisposeAsync(); throw; }
    }
    public async Task<string?> Read(CancellationToken stop) => await child.StandardOutput.ReadLineAsync(stop);
    public async Task Write(string message, CancellationToken stop)
    {
        await child.StandardInput.WriteLineAsync(message.AsMemory(), stop);
        await child.StandardInput.FlushAsync(stop);
    }
    public async ValueTask DisposeAsync()
    {
        if (disposed) return;
        disposed = true;
        child.StandardInput.Close();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        try { await child.WaitForExitAsync(deadline.Token); }
        catch (OperationCanceledException) { child.Kill(); await child.WaitForExitAsync(); }
        File.WriteAllText(Path.Combine(state, "linux.stderr.private.txt"), await error);
        // The Python owner process reaps its exact native process group before
        // normal exit. A killed Windows launcher alone is not that proof.
    }
}
