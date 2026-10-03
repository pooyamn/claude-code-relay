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
if (args[0] == "--lease-contender" && args.Length == 2 && Environment.MachineName == "DESKTOP-8SO9HDK")
{
    var called = false; var refused = false;
    try
    {
        await using var unexpected = NativeBroker.Own(Path.Combine(artifactRoot, "state"), artifactRoot, _ => {
            called = true; throw new InvalidOperationException("Contender must never start another native process"); });
    }
    catch (IOException error) when ((error.HResult & 0xffff) == 32) { refused = true; }
    File.WriteAllText(Path.Combine(artifactRoot, "state", "lease-contender.json"), JsonSerializer.Serialize(new { refused, nativeLauncherCalled = called }));
    if (!refused || called) throw new InvalidDataException("Kernel lease did not exclude contender before SQLite/native startup");
    return;
}
if (args[0] == "--client" && args.Length == 8 && args[4] is "first" or "second")
{
    var server = new WindowsPipePin(uint.Parse(args[2]), long.Parse(args[3]), exe, digest);
    await using var wire = await NativeBrokerWireClient.Connect(run, server, args[5], artifactRoot, deadline.Token);
    var observed = await wire.Status(deadline.Token);
    var clientReport = new Dictionary<string, object?> { ["complete"] = false, ["epoch"] = observed.Epoch, ["nativePid"] = observed.Pid };
    if (args[4] == "first")
    {
        var account = await Call("account/read", new { refreshToken = false });
        if (account.GetProperty("account").ValueKind != JsonValueKind.Null) throw new InvalidDataException("Diagnostic native unexpectedly authenticated");
        var remote = await Call("remoteControl/status/read", new { });
        if (remote.GetProperty("status").GetString() != "disabled") throw new InvalidDataException("Diagnostic native unexpectedly enrolled");
        var workspace = Path.Combine(@"C:\Users\pou\.native-remote", "broker-probe-" + run);
        var created = await Call("thread/start", new { cwd = workspace, ephemeral = false,
            approvalPolicy = "never", sandbox = "read-only", environments = Array.Empty<object>(), allowProviderModelFallback = false });
        var thread = created.GetProperty("thread").GetProperty("id").GetString()!;
        await Call("thread/inject_items", new { threadId = thread, items = new[] {
            new { type = "message", role = "user", content = new[] {
                new { type = "input_text", text = "[Inert broker checkpoint, not a task.] Never run models, tools or external actions." } } } } });
        clientReport["thread"] = thread; clientReport["cursor"] = (await wire.Status(deadline.Token)).Position;
        clientReport["nativeAccountAbsent"] = true; clientReport["nativeRemoteDisabled"] = true;
    }
    else
    {
        var cursor = long.Parse(args[6]); var thread = args[7];
        var events = await wire.Events(cursor, 100, deadline.Token);
        var methods = events.Where(e => e.Frame.TryGetProperty("params", out var p) && p.TryGetProperty("threadId", out var t) && t.GetString() == thread)
            .Select(e => e.Frame.GetProperty("method").GetString()).ToList();
        if (!methods.Contains("thread/goal/updated") || !methods.Contains("thread/goal/cleared")) throw new InvalidDataException("Wire offline native goal event custody incomplete");
        if (events.Any(e => e.Frame.TryGetProperty("method", out var m) && m.GetString() == "turn/started")) throw new InvalidDataException("Unexpected model turn");
        var read = await Call("thread/goal/get", new { threadId = thread });
        if (read.GetProperty("goal").ValueKind != JsonValueKind.Null) throw new InvalidDataException("Wire native goal readback mismatch");
        clientReport["receivedOfflineGoalUpdatedAndCleared"] = true; clientReport["goalReadbackMatched"] = true;
    }
    clientReport["complete"] = true;
    File.WriteAllText(Path.Combine(artifactRoot, "state", "client-" + args[4] + ".json"), JsonSerializer.Serialize(clientReport));
    return;
    async Task<JsonElement> Call(string method, object parameters)
    { Guard(method); return await wire.Call(Guid.NewGuid().ToString("N"), method, parameters, deadline.Token); }
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
    broker = NativeBroker.Own(state, artifactRoot, privateLedger => {
        ledger = privateLedger; nativeProcess = WindowsOwnerProcess.StartDiagnostic(policy, workspace, home);
        try { return rpc = new NativeRpc(nativeProcess, privateLedger); }
        catch { nativeProcess.Dispose(); throw; }
    });
    if (nativeProcess == null || ledger == null || rpc == null) throw new InvalidDataException("Owned diagnostic startup missing");
    var birth = nativeProcess.ObserveOwner(); report["nativeOwner"] = birth;
    await broker.Ready.WaitAsync(deadline.Token);
    stage = "independent-journal-contender";
    var sentinel = ledger.Attempt("diagnostic/lease-constructor-sentinel", new { });
    var contender = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true };
    contender.ArgumentList.Add("--lease-contender"); contender.ArgumentList.Add(run);
    client = Process.Start(contender) ?? throw new IOException("Lease contender missing");
    await client.WaitForExitAsync(deadline.Token);
    using (var receipt = JsonDocument.Parse(File.ReadAllText(Path.Combine(state, "lease-contender.json"))))
        if (client.ExitCode != 0 || !receipt.RootElement.GetProperty("refused").GetBoolean() || receipt.RootElement.GetProperty("nativeLauncherCalled").GetBoolean() ||
            ledger.Get("broker/current-epoch")!.Value.GetProperty("epoch").GetString() != broker.Epoch)
            throw new InvalidDataException("Contender reached live journal/native startup");
    // Read actual protected DB without constructing another Ledger: its
    // constructor would intentionally rewrite this sentinel on real recovery.
    // Only this diagnostic uses an attempting row with no external action.
    if (ledger.Unknown != 0) throw new InvalidDataException("Contender rewrote active constructor sentinel");
    report["independentKernelLeaseContenderDenied"] = true;
    report["contenderNativeLauncherNeverCalled"] = true;
    report["activeEpochAndConstructorSentinelUnchanged"] = true;
    client.Dispose(); client = null;
    var server = WindowsPipePeer.Capture(checked((uint)Environment.ProcessId), exe, digest);
    report["brokerServer"] = server; report["nativeEpoch"] = broker.Epoch;
    using var listener = new WindowsProtectedPipe(run);
    string? thread = null; long cursor = 0;
    for (var iteration = 0; iteration < 2; iteration++)
    {
        stage = "attached-client-" + iteration;
        var pending = listener.Stream.WaitForConnectionAsync(deadline.Token);
        var start = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { "--client", run, server.Pid.ToString(), server.CreationTime.ToString(), iteration == 0 ? "first" : "second",
            broker.Epoch, cursor.ToString(), thread ?? "-" }) start.ArgumentList.Add(arg);
        client = Process.Start(start) ?? throw new IOException("Protected fixture client missing");
        var pin = WindowsPipePeer.Capture(checked((uint)client.Id), exe, digest);
        await pending;
        var serving = NativeBrokerWire.Serve(broker, listener.Stream, pin, artifactRoot, request => {
            if (request.Kind == "call") Guard(request.Method!);
            else if (request.Kind is not ("status" or "events")) throw new InvalidDataException("Fixed fixture wire methods only");
        }, deadline.Token);
        await client.WaitForExitAsync(deadline.Token); await serving.WaitAsync(deadline.Token);
        if (client.ExitCode != 0) throw new InvalidDataException("Protected wire client failed");
        using (var receipt = JsonDocument.Parse(File.ReadAllText(Path.Combine(state, iteration == 0 ? "client-first.json" : "client-second.json"))))
        {
            var verified = receipt.RootElement;
            if (!verified.GetProperty("complete").GetBoolean() || verified.GetProperty("epoch").GetString() != broker.Epoch ||
                verified.GetProperty("nativePid").GetUInt32() != broker.Pid || nativeProcess.ObserveOwner() != birth)
                throw new InvalidDataException("Wire client native generation mismatch");
            if (iteration == 0)
            {
                thread = verified.GetProperty("thread").GetString(); cursor = verified.GetProperty("cursor").GetInt64();
                report["nativeAccountAbsent"] = true; report["nativeRemoteDisabled"] = true; report["diagnosticThreadCheckpointed"] = true;
            }
            else
            {
                if (!verified.GetProperty("receivedOfflineGoalUpdatedAndCleared").GetBoolean() || !verified.GetProperty("goalReadbackMatched").GetBoolean() || broker.Unknown != 0)
                    throw new InvalidDataException("Native identity/goal/intent custody differs after client replacement");
                report["secondClientReceivedOfflineGoalUpdatedAndCleared"] = true;
                report["secondClientGoalReadbackMatched"] = true;
                report["sameNativeProcessGenerationAfterClientReplacement"] = true;
            }
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
    report["crossProcessNativeCallsAndEventsUsedBrokerWire"] = true;
    report["complete"] = true;
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
