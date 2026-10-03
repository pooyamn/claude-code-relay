using System.ComponentModel;
using System.Diagnostics;
using System.IO.Pipes;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using KhadangRouter;

// Deterministic kernel transport test only. No native/model process, provider
// credentials, network, Telegram, live ledger, enrollment or production policy.
if (args.SequenceEqual(new[] { "--self-test" }))
{
    var checks = 0;
    var good = new WindowsPipePin(42, 1, @"C:\Protected\fixture.exe", new string('a', 64)); good.Validate(); checks++;
    foreach (var pin in new[] { good with { Pid = 0 }, good with { CreationTime = 0 }, good with { Sha256 = "a" },
        good with { Sha256 = new string('z', 64) }, good with { Image = @"\\server\fixture.exe" }, good with { Image = @"C:\..\fixture.exe" } })
    {
        try { pin.Validate(); throw new Exception("Unsafe process pin accepted"); }
        catch (InvalidDataException) { checks++; }
    }
    WindowsProtectedPipe.Name(Guid.NewGuid().ToString("N")); checks++;
    foreach (var run in new[] { "", "../x", "a/b", Guid.NewGuid().ToString("D") })
    {
        try { WindowsProtectedPipe.Name(run); throw new Exception("Unsafe endpoint name accepted"); }
        catch (InvalidDataException) { checks++; }
    }
    Console.WriteLine($"{checks} protected-pipe argument checks passed (no credentials/network/models)."); return;
}
if (!OperatingSystem.IsWindows() || args.Length < 2 || !Guid.TryParseExact(args[1], "N", out _))
    throw new InvalidDataException("Windows one-shot protected-pipe fixture and exact run ID required");
var runId = args[1]; var root = Path.GetDirectoryName(AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar))!;
var state = Path.Combine(root, "state"); var exe = Environment.ProcessPath!;
var digest = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(exe)));
using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(45));
if (args[0] == "--client" && args.Length == 4)
{
    WindowsPipePeer.RequireSystem();
    var server = new WindowsPipePin(uint.Parse(args[2]), long.Parse(args[3]), exe, digest);
    var (stream, peer) = await WindowsPipePeer.Connect(runId, server, root, deadline.Token);
    using (stream) using (peer)
    {
        foreach (var bad in new[] { server with { Pid = checked((uint)Environment.ProcessId) },
            server with { CreationTime = server.CreationTime + 1 }, server with { Sha256 = new string('0', 64) },
            server with { Image = @"C:\Windows\System32\not-this-fixture.exe" } })
        {
            try { using var denied = WindowsPipePeer.Authenticate(stream, true, bad, root); throw new Exception("Forged server pin accepted"); }
            catch (InvalidDataException) { }
        }
        peer.Current();
        using var writer = new StreamWriter(stream, new UTF8Encoding(false), leaveOpen: true) { AutoFlush = true };
        await writer.WriteLineAsync("fixture-client".AsMemory(), deadline.Token);
        using var reader = new StreamReader(stream, Encoding.UTF8, leaveOpen: true);
        if (await reader.ReadLineAsync(deadline.Token) != "fixture-accepted") throw new InvalidDataException("Fixture peer exchange failed");
        peer.Current();
    }
    return;
}
if (args[0] == "--owner-denial" && args.Length == 2)
{
    using var identity = WindowsIdentity.GetCurrent();
    if (identity.User?.Value != "S-1-5-21-71459778-1164188569-2276148161-1001" || identity.IsSystem ||
        new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator) || Process.GetCurrentProcess().SessionId != 1)
        throw new InvalidDataException("Exact ordinary console owner required for denial test");
    var componentDenied = false;
    try { WindowsPipePeer.RequireSystem(); } catch (InvalidDataException) { componentDenied = true; }
    var accessDenied = false;
    using (var client = new NamedPipeClientStream(".", WindowsProtectedPipe.Name(runId), PipeDirection.InOut,
        PipeOptions.Asynchronous, TokenImpersonationLevel.Identification))
    {
        try { await client.ConnectAsync(deadline.Token); }
        catch (UnauthorizedAccessException) { accessDenied = true; }
    }
    if (!componentDenied || !accessDenied) throw new InvalidDataException("Owner was not explicitly denied at the kernel/component boundary");
    var privateState = Path.Combine(@"C:\Users\pou\.native-remote", "pipe-owner-denial-" + runId);
    if (Directory.Exists(privateState)) throw new InvalidDataException("Previous owner fixture exists; no replay");
    Directory.CreateDirectory(privateState);
    File.WriteAllText(Path.Combine(privateState, "result.json"), JsonSerializer.Serialize(new {
        complete = true, accessDenied, componentDenied, sid = identity.User.Value, elevated = false, session = 1,
        observedAt = DateTimeOffset.UtcNow, productionChanged = false, modelsStarted = false }));
    return;
}
if (args[0] != "--run" || args.Length != 2) throw new InvalidDataException("Unknown fixture invocation");
WindowsPipePeer.RequireSystem();
var result = new Dictionary<string, object?> { ["schema"] = "ccrelay.windows_pipe_peer_probe.v1", ["complete"] = false,
    ["productionChanged"] = false, ["modelsStarted"] = false, ["brokerNativeLifetimeVerified"] = false };
Process? owned = null; var stage = "claim";
try
{
    Directory.CreateDirectory(state);
    using var claim = new FileStream(Path.Combine(state, "one-shot.claim"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
    claim.Flush(true);
    var self = WindowsPipePeer.Capture(checked((uint)Environment.ProcessId), exe, digest);
    result["serverPin"] = self;
    using var listener = new WindowsProtectedPipe(runId);
    stage = "second-first-instance-denial";
    try { using var collision = new WindowsProtectedPipe(runId); throw new Exception("Second first-instance created"); }
    // With maxInstances=1 Windows can enforce the instance ceiling first
    // (ERROR_PIPE_BUSY=231), before FIRST_INSTANCE's ACCESS_DENIED=5 check.
    // Both are explicit failed creates, not a timeout or relaxed auth decision.
    catch (Win32Exception error) when (error.NativeErrorCode is 5 or 231)
    { result["secondFirstInstanceExplicitlyDenied"] = true; result["secondFirstInstanceWin32Code"] = error.NativeErrorCode; }
    // Positive reconnects use two independently held, exact child generations.
    // No model or credential helper is spawned as SYSTEM: only this fixture.
    for (var iteration = 0; iteration < 2; iteration++)
    {
        stage = "kernel-peer-" + iteration;
        var pending = listener.Stream.WaitForConnectionAsync(deadline.Token);
        var start = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { "--client", runId, self.Pid.ToString(), self.CreationTime.ToString() }) start.ArgumentList.Add(arg);
        owned = Process.Start(start) ?? throw new IOException("Fixture child did not start");
        var childPin = WindowsPipePeer.Capture(checked((uint)owned.Id), exe, digest);
        await pending;
        foreach (var bad in new[] { childPin with { Pid = self.Pid }, childPin with { CreationTime = childPin.CreationTime + 1 },
            childPin with { Sha256 = new string('0', 64) }, childPin with { Image = @"C:\Windows\System32\not-this-fixture.exe" } })
        {
            try { using var denied = WindowsPipePeer.Authenticate(listener.Stream, false, bad, root); throw new Exception("Forged peer pin accepted"); }
            catch (InvalidDataException) { }
        }
        using (var peer = WindowsPipePeer.Authenticate(listener.Stream, false, childPin, root))
        {
            peer.Current();
            using var reader = new StreamReader(listener.Stream, Encoding.UTF8, leaveOpen: true);
            if (await reader.ReadLineAsync(deadline.Token) != "fixture-client") throw new InvalidDataException("Unexpected fixture data");
            using var writer = new StreamWriter(listener.Stream, new UTF8Encoding(false), leaveOpen: true) { AutoFlush = true };
            await writer.WriteLineAsync("fixture-accepted".AsMemory(), deadline.Token);
            await owned.WaitForExitAsync(deadline.Token);
            if (owned.ExitCode != 0) throw new InvalidDataException("Mutual server authentication failed");
            try { peer.Current(); throw new Exception("Exited peer grant accepted"); } catch (InvalidDataException) { }
        }
        listener.Stream.Disconnect(); owned.Dispose(); owned = null;
        result["mutuallyAuthenticatedConnections"] = iteration + 1;
    }
    result["forgedPidGenerationImageAndBytesDenied"] = true;
    result["exitedPeerGrantDenied"] = true;
    result["sameServerGenerationAfterClientDisconnect"] = WindowsPipePeer.Capture(self.Pid, exe, digest) == self;
    // Keep this first-instance listener available for the limited-owner task.
    // The coordinator starts that task only after this protected ready record.
    File.WriteAllText(Path.Combine(state, "owner-denial-ready.json"), JsonSerializer.Serialize(new { server = self, observedAt = DateTimeOffset.UtcNow }));
    stage = "owner-denial-window";
    var pendingOwner = listener.Stream.WaitForConnectionAsync(deadline.Token);
    var marker = Path.Combine(root, "owner-denial-observed.json");
    while (!File.Exists(marker))
    {
        if (pendingOwner.IsCompleted) throw new InvalidDataException("Unexpected client entered owner-denial endpoint");
        await Task.Delay(100, deadline.Token); // observation only, no mutation retry
    }
    if (pendingOwner.IsCompleted) throw new InvalidDataException("Unexpected client entered owner-denial endpoint");
    result["ownerDenialWindowHadNoAcceptedConnection"] = true;
    result["complete"] = true;
}
catch (Exception error)
{
    result["failedStage"] = stage; result["errorType"] = error.GetType().Name;
    if (error is Win32Exception native) result["win32Code"] = native.NativeErrorCode;
    Environment.ExitCode = 1;
}
finally
{
    if (owned != null) { if (!owned.HasExited) owned.Kill(); owned.Dispose(); }
    result["observedAt"] = DateTimeOffset.UtcNow;
    File.WriteAllText(Path.Combine(state, "result.json"), JsonSerializer.Serialize(result));
}
