using System.Diagnostics;
using System.Security.Principal;
using System.Text.Json;
using KhadangRouter;

// Exercise the frozen router's NativeRpc across Windows stdio -> WSL -> the
// SAME Linux native Unix listener. Never poll Telegram or use owner history/auth.
if (args.SequenceEqual(new[] { "--self-test" }))
{
    foreach (var method in new[] { "turn/start", "turn/steer", "account/login/start", "remoteControl/enable" })
    {
        try { Allowed(method); throw new InvalidOperationException("Unsafe diagnostic method accepted"); }
        catch (InvalidDataException) { }
    }
    Console.WriteLine("Linux native probe method guards pass; no native/model/network activity.");
    return;
}
string? state = null;
BridgeChannel? firstChannel = null, secondChannel = null;
var report = new Dictionary<string, object?> { ["complete"] = false, ["modelsStarted"] = false,
    ["productionChanged"] = false, ["existingConversationsResumed"] = false, ["phoneRoundTripVerified"] = false };
try
{
    if (!OperatingSystem.IsWindows() || args.Length != 2 || args[0] != "--run" || !Guid.TryParseExact(args[1], "N", out var run))
        throw new InvalidDataException("Exact Windows migration diagnostic run required");
    using var identity = WindowsIdentity.GetCurrent();
    if (Environment.MachineName != "DESKTOP-8SO9HDK" || identity.User?.Value != "S-1-5-21-71459778-1164188569-2276148161-1001" ||
        identity.IsSystem || new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator) || Process.GetCurrentProcess().SessionId != 1)
        throw new InvalidDataException("Exact non-elevated interactive owner in session 1 required");
    report["ownerSid"] = identity.User.Value; report["windowsSession"] = 1; report["elevated"] = false;
    var denied = false;
    try { using var file = File.OpenRead(@"C:\ProgramData\KhadangRouter\khadang-token.dpapi"); }
    catch (UnauthorizedAccessException) { denied = true; }
    if (!denied) throw new InvalidDataException("Actual protected bot credential denial required");
    report["windowsCredentialReadDenied"] = true;
    state = @"C:\Users\pou\.native-remote\migration-linux-transport-" + run.ToString("N");
    if (Directory.Exists(state) || File.Exists(state)) throw new InvalidDataException("Prior attempt preserved; never replay");
    Directory.CreateDirectory(state);
    using var claim = new FileStream(Path.Combine(state, "one-shot.claim"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
    var release = "/mnt/c/ProgramData/OracovaNativeRemote/migration-linux-transport-" + run.ToString("N");
    using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(90));
    firstChannel = await BridgeChannel.Start(release + "/check-pc-native-transport.py", "--run", run.ToString("N"), state, "first", stop.Token);
    secondChannel = await BridgeChannel.Start(release + "/pc_native_stdio.py", "--socket", firstChannel.Ready.GetProperty("socket").GetString()!, state, "second", stop.Token);
    if (firstChannel.Ready.GetProperty("peerPid").GetInt32() != secondChannel.Ready.GetProperty("peerPid").GetInt32() ||
        firstChannel.Ready.GetProperty("peerGeneration").GetString() != secondChannel.Ready.GetProperty("peerGeneration").GetString())
        throw new InvalidDataException("Clients do not share one live native process generation");
    report["nativeLinuxPid"] = firstChannel.Ready.GetProperty("peerPid").GetInt32();
    report["linuxUid"] = 1000; report["clients"] = 2;
    using var firstLedger = new Ledger(Path.Combine(state, "first.db"));
    using var secondLedger = new Ledger(Path.Combine(state, "second.db"));
    await using var first = new NativeRpc(firstChannel, firstLedger);
    await using var second = new NativeRpc(secondChannel, secondLedger);
    await first.Initialize(stop.Token); await second.Initialize(stop.Token);
    foreach (var rpc in new[] { first, second })
    {
        var account = await Call(rpc, "account/read", new { refreshToken = false }, stop.Token);
        if (account.GetProperty("account").ValueKind != JsonValueKind.Null) throw new InvalidDataException("Diagnostic unexpectedly authenticated");
        var loaded = await Call(rpc, "thread/loaded/list", new { }, stop.Token);
        if (loaded.GetProperty("data").GetArrayLength() != 0) throw new InvalidDataException("Existing task unexpectedly loaded");
    }
    report["nativeAccountAbsent"] = true;
    var linuxWorkspace = "/Users/pouya/.migration/native-transport-" + run.ToString("N");
    var uid = await Call(first, "command/exec", new { command = new[] { "/usr/bin/id", "-u" }, cwd = linuxWorkspace,
        sandboxPolicy = new { type = "dangerFullAccess" }, timeoutMs = 10000 }, stop.Token);
    if (uid.GetProperty("exitCode").GetInt32() != 0 || uid.GetProperty("stdout").GetString()!.Trim() != "1000")
        throw new InvalidDataException("Actual Linux native tool identity mismatch");
    var check = "import os,errno,sys\ntry:\n f=os.open('/mnt/c/ProgramData/KhadangRouter/khadang-token.dpapi',os.O_RDONLY);os.close(f);sys.exit(20)\nexcept OSError as e:\n sys.exit(0 if e.errno in (errno.EACCES,errno.EPERM) else 21)";
    var boundary = await Call(first, "command/exec", new { command = new[] { "/usr/bin/python3", "-I", "-c", check }, cwd = linuxWorkspace,
        sandboxPolicy = new { type = "dangerFullAccess" }, timeoutMs = 10000 }, stop.Token);
    if (boundary.GetProperty("exitCode").GetInt32() != 0) throw new InvalidDataException("Actual native tool could access protected bot credential");
    report["nativeToolCredentialReadDenied"] = true; report["nativeToolUid"] = 1000;
    var started = await Call(first, "thread/start", new { cwd = linuxWorkspace, sandbox = "read-only", approvalPolicy = "never",
        environments = Array.Empty<object>(), allowProviderModelFallback = false }, stop.Token);
    var thread = started.GetProperty("thread").GetProperty("id").GetString()!;
    if (started.GetProperty("cwd").GetString() != linuxWorkspace) throw new InvalidDataException("Wrong diagnostic workspace");
    await Call(first, "thread/inject_items", new { threadId = thread, items = new[] { new { type = "message", role = "user",
        content = new[] { new { type = "input_text", text = "[Inert transport checkpoint, not a task.] Never run a model or external action." } } } } }, stop.Token);
    var resumed = await Call(second, "thread/resume", new { threadId = thread, excludeTurns = true }, stop.Token);
    if (resumed.GetProperty("thread").GetProperty("id").GetString() != thread || resumed.GetProperty("cwd").GetString() != linuxWorkspace)
        throw new InvalidDataException("Second client did not attach to exact diagnostic thread");
    var changed = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
    var cleared = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
    var turns = 0;
    void Observe(JsonElement message)
    {
        if (!message.TryGetProperty("method", out var m) || !message.TryGetProperty("params", out var p) ||
            !p.TryGetProperty("threadId", out var id) || id.GetString() != thread) return;
        if (m.GetString() == "turn/started") Interlocked.Increment(ref turns);
        if (m.GetString() == "thread/goal/updated" && p.TryGetProperty("goal", out var goal))
        {
            if (goal.ValueKind == JsonValueKind.Object && goal.GetProperty("objective").GetString() == "Paused Linux transport diagnostic" &&
                goal.GetProperty("status").GetString() == "paused") changed.TrySetResult();
        }
        // The existing router/Windows probe already establishes this separate
        // native event. A null goal/updated is not the clear delivery receipt.
        if (m.GetString() == "thread/goal/cleared") cleared.TrySetResult();
    }
    second.Notification += Observe;
    try
    {
        await Call(first, "thread/goal/set", new { threadId = thread, objective = "Paused Linux transport diagnostic", status = "paused" }, stop.Token);
        await changed.Task.WaitAsync(TimeSpan.FromSeconds(5), stop.Token);
        var read = await Call(second, "thread/goal/get", new { threadId = thread }, stop.Token);
        if (read.GetProperty("goal").GetProperty("status").GetString() != "paused") throw new InvalidDataException("Goal state did not share across clients");
        await Call(first, "thread/goal/clear", new { threadId = thread }, stop.Token);
        await cleared.Task.WaitAsync(TimeSpan.FromSeconds(5), stop.Token);
        var empty = await Call(second, "thread/goal/get", new { threadId = thread }, stop.Token);
        if (empty.GetProperty("goal").ValueKind != JsonValueKind.Null) throw new InvalidDataException("Diagnostic goal remained after clear");
        if (turns != 0 || firstLedger.Unknown != 0 || secondLedger.Unknown != 0) throw new InvalidDataException("Unexpected model turn or unknown diagnostic outcome");
        report["crossClientPausedGoalEvents"] = true; report["crossClientGoalUpdatedAndCleared"] = true;
        report["observedTurnStarts"] = 0; report["unknownDiagnosticEffects"] = 0;
    }
    finally { second.Notification -= Observe; }
    report["complete"] = true;
}
catch (Exception error)
{
    report["complete"] = false;
    report["errorType"] = error.GetType().Name;
    if (state != null) File.WriteAllText(Path.Combine(state, "failure.private.txt"), error.ToString());
    Environment.ExitCode = 1;
}
finally
{
    if (secondChannel != null) await secondChannel.DisposeAsync();
    if (firstChannel != null) await firstChannel.DisposeAsync();
    report["launchersStopped"] = (firstChannel?.Exited ?? true) && (secondChannel?.Exited ?? true);
    report["at"] = DateTimeOffset.UtcNow;
    if (state != null) File.WriteAllText(Path.Combine(state, "result.json"), JsonSerializer.Serialize(report));
    Console.WriteLine(JsonSerializer.Serialize(report));
}

static void Allowed(string method)
{
    if (method is "account/read" or "thread/loaded/list" or "command/exec" or "thread/start" or
        "thread/resume" or "thread/inject_items" or "thread/goal/set" or "thread/goal/get" or "thread/goal/clear") return;
    throw new InvalidDataException("Method is outside credential-free transport diagnostic scope");
}
static Task<JsonElement> Call(NativeRpc rpc, string method, object parameters, CancellationToken stop)
{
    Allowed(method);
    return rpc.Call(method, parameters, stop, effect: method is not ("account/read" or "thread/loaded/list" or "thread/goal/get"));
}

sealed class BridgeChannel(Process child, string state, string label) : INativeChannel
{
    private readonly Task<string> stderr = child.StandardError.ReadToEndAsync();
    private bool disposed;
    public JsonElement Ready { get; private set; }
    public uint Pid => checked((uint)child.Id); // Windows launcher observation, NOT Linux native PID.
    public bool Exited => child.HasExited;
    public static async Task<BridgeChannel> Start(string script, string option, string value, string state, string label, CancellationToken stop)
    {
        var launch = new ProcessStartInfo(@"C:\Windows\System32\wsl.exe") { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in new[] { "-d", "Ubuntu-24.04", "-u", "pou", "--exec", "/usr/bin/python3", "-I", "-B", script, option, value }) launch.ArgumentList.Add(argument);
        var process = Process.Start(launch) ?? throw new IOException("Owned bridge did not start");
        var result = new BridgeChannel(process, state, label);
        try
        {
            var line = await result.Read(stop) ?? throw new IOException("Bridge ended before ready");
            using var document = JsonDocument.Parse(line);
            if (document.RootElement.GetProperty("method").GetString() != "ccrelay/transport/ready") throw new InvalidDataException("Wrong bridge readiness frame");
            result.Ready = document.RootElement.GetProperty("params").Clone();
            if (result.Ready.GetProperty("uid").GetInt32() != 1000 || result.Ready.GetProperty("peerUid").GetInt32() != 1000)
                throw new InvalidDataException("Wrong ordinary Linux owner or native peer");
            return result;
        }
        catch { await result.DisposeAsync(); throw; }
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
        File.WriteAllText(Path.Combine(state, label + ".stderr.private.txt"), await stderr);
    }
}
