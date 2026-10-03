using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using KhadangRouter;

// Fixed, credential-free custody test, never a live broker/service activation.
// SYSTEM runs only this deterministic host/client code. The owned native process
// uses the exact non-elevated console owner and an empty child-only native home.
if (args.SequenceEqual(new[] { "--self-test" }))
{
    var checks = 0;
    foreach (var method in new[] { "account/read", "remoteControl/status/read", "thread/start", "thread/inject_items", "thread/goal/set", "thread/goal/clear", "thread/goal/get" })
    { Guard(method); checks++; }
    foreach (var method in new[] { "turn/start", "turn/steer", "command/exec", "remoteControl/enable", "account/login/start" })
    {
        try { Guard(method); throw new Exception("Model/auth/tool operation accepted"); } catch (InvalidDataException) { checks++; }
    }
    Console.WriteLine($"{checks} broker-probe method guards passed (no credentials/network/models)."); return;
}
if (!OperatingSystem.IsWindows() || args.Length < 2 || !Guid.TryParseExact(args[1], "N", out _))
    throw new InvalidDataException("Windows exact one-shot broker test required");
WindowsPipePeer.RequireSystem();
var run = args[1]; var exe = Environment.ProcessPath!;
var artifactRoot = Path.GetDirectoryName(AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar))!;
var digest = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(exe)));
using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60));
if (args[0] == "--client" && args.Length == 5 && args[4] is "first" or "second")
{
    var server = new WindowsPipePin(uint.Parse(args[2]), long.Parse(args[3]), exe, digest);
    var (stream, peer) = await WindowsPipePeer.Connect(run, server, artifactRoot, deadline.Token);
    using (stream) using (peer)
    {
        using var writer = new StreamWriter(stream, new UTF8Encoding(false), leaveOpen: true) { AutoFlush = true };
        using var reader = new StreamReader(stream, Encoding.UTF8, leaveOpen: true);
        await writer.WriteLineAsync(args[4].AsMemory(), deadline.Token);
        var line = await reader.ReadLineAsync(deadline.Token) ?? throw new IOException("Broker fixture response missing");
        if (line.Length > 4096) throw new InvalidDataException("Unexpected broker fixture frame size");
        using var response = JsonDocument.Parse(line);
        if (!response.RootElement.GetProperty("verified").GetBoolean()) throw new InvalidDataException("Broker fixture verification failed");
        peer.Current();
    }
    return;
}
if (args[0] != "--run" || args.Length != 2 || Environment.MachineName != "DESKTOP-8SO9HDK")
    throw new InvalidDataException("Exact PC deterministic fixture required");
var state = Path.Combine(artifactRoot, "state");
if (File.Exists(Path.Combine(state, "one-shot.claim"))) throw new InvalidDataException("Previous broker fixture exists; never replay/overwrite");
using var claim = new FileStream(Path.Combine(state, "one-shot.claim"), FileMode.CreateNew, FileAccess.Write, FileShare.None); claim.Flush(true);
var report = new Dictionary<string, object?> { ["schema"] = "ccrelay.native_broker_probe.v1", ["complete"] = false,
    ["modelsStarted"] = false, ["productionChanged"] = false, ["remoteEnrollment"] = false, ["phoneRoundTripVerified"] = false };
WindowsOwnerProcess? nativeProcess = null; NativeBroker? broker = null; Ledger? ledger = null; NativeRpc? rpc = null; Process? client = null;
var stage = "owned-native-launch";
try
{
    const string ownerRoot = @"C:\Users\pou\.native-remote";
    var workspace = Path.Combine(ownerRoot, "broker-probe-" + run); var home = Path.Combine(workspace, "empty-native-home");
    var policy = new RouterPolicy("TheKhadangBot", 123, 456, -100123, "S-1-5-21-71459778-1164188569-2276148161-1001",
        @"C:\Users\pou\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe", "FDDA5FA3CF3FB3D000B876720742857676293E4315E4B045FAE6F8BD7E866D1D",
        Path.Combine(artifactRoot, "unused-credential"), state, ownerRoot);
    nativeProcess = WindowsOwnerProcess.StartDiagnostic(policy, workspace, home);
    var birth = nativeProcess.ObserveOwner(); report["nativeOwner"] = birth;
    ledger = new Ledger(Path.Combine(state, "broker.db"));
    rpc = new NativeRpc(nativeProcess, ledger); broker = NativeBroker.Own(rpc, ledger);
    await broker.Ready.WaitAsync(deadline.Token);
    var server = WindowsPipePeer.Capture(checked((uint)Environment.ProcessId), exe, digest);
    report["brokerServer"] = server; report["nativeEpoch"] = broker.Epoch;
    using var listener = new WindowsProtectedPipe(run);
    string? thread = null; long cursor = 0;
    for (var iteration = 0; iteration < 2; iteration++)
    {
        stage = "attached-client-" + iteration;
        var pending = listener.Stream.WaitForConnectionAsync(deadline.Token);
        var start = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { "--client", run, server.Pid.ToString(), server.CreationTime.ToString(), iteration == 0 ? "first" : "second" }) start.ArgumentList.Add(arg);
        client = Process.Start(start) ?? throw new IOException("Protected fixture client missing");
        var pin = WindowsPipePeer.Capture(checked((uint)client.Id), exe, digest);
        await pending;
        using (var peer = WindowsPipePeer.Authenticate(listener.Stream, false, pin, artifactRoot))
        using (var attached = broker.Attach(peer))
        {
            using var reader = new StreamReader(listener.Stream, Encoding.UTF8, leaveOpen: true);
            if (await reader.ReadLineAsync(deadline.Token) != (iteration == 0 ? "first" : "second")) throw new InvalidDataException("Unexpected fixture client stage");
            if (iteration == 0)
            {
                var account = await Call(attached, "account/read", new { refreshToken = false });
                if (account.GetProperty("account").ValueKind != JsonValueKind.Null) throw new InvalidDataException("Diagnostic native unexpectedly authenticated");
                var remote = await Call(attached, "remoteControl/status/read", new { });
                if (remote.GetProperty("status").GetString() != "disabled") throw new InvalidDataException("Diagnostic native unexpectedly enrolled");
                var created = await Call(attached, "thread/start", new { cwd = workspace, ephemeral = false,
                    approvalPolicy = "never", sandbox = "read-only", environments = Array.Empty<object>(), allowProviderModelFallback = false });
                thread = created.GetProperty("thread").GetProperty("id").GetString()!;
                await Call(attached, "thread/inject_items", new { threadId = thread, items = new[] {
                    new { type = "message", role = "user", content = new[] {
                        new { type = "input_text", text = "[Inert broker checkpoint, not a task.] Never run models, tools or external actions." } } } } });
                cursor = broker.Position;
                report["nativeAccountAbsent"] = true; report["nativeRemoteDisabled"] = true; report["diagnosticThreadCheckpointed"] = true;
            }
            else
            {
                var events = attached.Events(cursor);
                var methods = events.Where(e => e.Frame.TryGetProperty("params", out var p) && p.TryGetProperty("threadId", out var t) && t.GetString() == thread)
                    .Select(e => e.Frame.GetProperty("method").GetString()).ToList();
                if (!methods.Contains("thread/goal/updated") || !methods.Contains("thread/goal/cleared")) throw new InvalidDataException("Offline native goal event custody incomplete");
                if (events.Where(e => e.Frame.TryGetProperty("method", out var m) && m.GetString() == "turn/started").Any())
                    throw new InvalidDataException("Unexpected model turn");
                var read = await Call(attached, "thread/goal/get", new { threadId = thread });
                if (read.GetProperty("goal").ValueKind != JsonValueKind.Null || nativeProcess.ObserveOwner() != birth || broker.Unknown != 0)
                    throw new InvalidDataException("Native identity/goal/intent custody differs after client replacement");
                report["secondClientReceivedOfflineGoalUpdatedAndCleared"] = true;
                report["secondClientGoalReadbackMatched"] = true;
                report["sameNativeProcessGenerationAfterClientReplacement"] = true;
            }
            using var writer = new StreamWriter(listener.Stream, new UTF8Encoding(false), leaveOpen: true) { AutoFlush = true };
            await writer.WriteLineAsync("{\"verified\":true}".AsMemory(), deadline.Token);
            await client.WaitForExitAsync(deadline.Token);
            if (client.ExitCode != 0) throw new InvalidDataException("Protected client failed");
        }
        listener.Stream.Disconnect(); client.Dispose(); client = null;
        if (iteration == 0)
        {
            stage = "offline-native-events";
            if (nativeProcess.ObserveOwner() != birth) throw new InvalidDataException("Client exit killed/replaced native process");
            // Fixed same-process protected diagnostic supervisor, not a hidden
            // UI source, inference, arbitrary shell or production admission path.
            await Control("thread/goal/set", new { threadId = thread, objective = "Inert paused broker test " + run, status = "paused" });
            await Control("thread/goal/clear", new { threadId = thread });
            // Read-only observation until both real stream events reach custody;
            // never retry either goal mutation or reopen a native transport.
            using var observe = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token); observe.CancelAfter(TimeSpan.FromSeconds(10));
            while (true)
            {
                var methods = broker.ControllerEvents(cursor).Where(e => e.Frame.TryGetProperty("params", out var p) &&
                    p.TryGetProperty("threadId", out var t) && t.GetString() == thread).Select(e => e.Frame.GetProperty("method").GetString()).ToList();
                if (methods.Contains("thread/goal/updated") && methods.Contains("thread/goal/cleared")) break;
                await Task.Delay(50, observe.Token);
            }
        }
    }
    report["unknownDiagnosticIntents"] = broker.Unknown; report["eventPosition"] = broker.Position;
    if (rpc.InitializationAttempts != 1) throw new InvalidDataException("Native initialization count changed across UI clients");
    report["nativeInitializationCount"] = rpc.InitializationAttempts;
    report["complete"] = true;
    async Task<JsonElement> Call(NativeBrokerSession attached, string method, object parameters)
    { Guard(method); return await attached.Call(Guid.NewGuid().ToString("N"), method, parameters, deadline.Token); }
    async Task<JsonElement> Control(string method, object parameters)
    { Guard(method); return await broker.ControllerCall(Guid.NewGuid().ToString("N"), method, parameters, deadline.Token); }
}
catch (Exception error)
{
    report["failedStage"] = stage; report["errorType"] = error.GetType().Name;
    if (error is System.ComponentModel.Win32Exception native) report["win32Code"] = native.NativeErrorCode;
    Environment.ExitCode = 1;
}
finally
{
    if (client != null) { if (!client.HasExited) client.Kill(); client.Dispose(); }
    if (broker != null) await broker.DisposeAsync();
    else if (rpc != null) { await rpc.DisposeAsync(); ledger?.Dispose(); }
    else { nativeProcess?.Dispose(); ledger?.Dispose(); }
    report["observedAt"] = DateTimeOffset.UtcNow;
    File.WriteAllText(Path.Combine(state, "result.json"), JsonSerializer.Serialize(report));
}
static void Guard(string method)
{
    if (method is not ("account/read" or "remoteControl/status/read" or "thread/start" or "thread/inject_items" or "thread/goal/set" or "thread/goal/clear" or "thread/goal/get"))
        throw new InvalidDataException("Broker fixture refuses models, tools, login and enrollment");
}
