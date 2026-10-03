using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;

// Transport acceptance only. No production credential/home, router ledger,
// Telegram poller, enrollment, thread resume, model or shell/tool invocation.
if (args.SequenceEqual(new[] { "--self-test" }))
{
    var checks = 0;
    foreach (var method in new[] { "initialize", "account/read", "remoteControl/status/read", "thread/loaded/list" })
    { Rpc.Allowed(method); checks++; }
    foreach (var method in new[] { "turn/start", "thread/resume", "remoteControl/enable", "account/login/start", "command/exec" })
    {
        try { Rpc.Allowed(method); throw new Exception("Mutation accepted"); }
        catch (InvalidDataException) { checks++; }
    }
    Console.WriteLine($"{checks} sharing-probe method guards passed; no credentials/network/models.");
    return;
}

string? state = null;
Process? child = null;
Task<string>? output = null, error = null;
var stage = "identity";
var report = new Dictionary<string, object?> { ["schema"] = "ccrelay.native_sharing_probe.v1", ["complete"] = false,
    ["productionChanged"] = false, ["modelTurns"] = 0, ["remoteEnrollment"] = false,
    ["isolatedCredentialFreeHome"] = true, ["phoneRoundTripVerified"] = false };
try
{
    if (!OperatingSystem.IsWindows() || args.Length != 2 || args[0] != "--run" || !Guid.TryParseExact(args[1], "N", out var run))
        throw new InvalidDataException("Windows one-shot probe requires a run ID");
    using var identity = WindowsIdentity.GetCurrent();
    var elevated = new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
    var session = Process.GetCurrentProcess().SessionId;
    if (Environment.MachineName != "DESKTOP-8SO9HDK" || identity.User?.Value != "S-1-5-21-71459778-1164188569-2276148161-1001" ||
        identity.IsSystem || elevated || session != 1) throw new InvalidDataException("Exact non-elevated console owner required");
    report["ownerSid"] = identity.User.Value; report["elevated"] = false; report["sessionId"] = session;
    const string exe = @"C:\Users\pou\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe";
    if ((File.GetAttributes(exe) & FileAttributes.ReparsePoint) != 0 ||
        Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(exe))) != "FDDA5FA3CF3FB3D000B876720742857676293E4315E4B045FAE6F8BD7E866D1D")
        throw new InvalidDataException("Pinned native executable required");
    const string parent = @"C:\Users\pou\.native-remote";
    for (var part = new DirectoryInfo(parent); part != null; part = part.Parent)
        if (!part.Exists || (part.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Literal private parent required");
    var candidate = Path.Combine(parent, "sharing-probe-" + run.ToString("N"));
    if (Directory.Exists(candidate) || File.Exists(candidate)) throw new InvalidDataException("Prior probe exists; never replay");
    state = candidate;
    Directory.CreateDirectory(state);
    using var claim = new FileStream(Path.Combine(state, "one-shot.claim"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
    claim.Flush(true);
    var freshHome = Path.Combine(state, "empty-native-home"); Directory.CreateDirectory(freshHome);
    // Reserve an ephemeral loopback endpoint, then release it for the native
    // server. A bind race is a failed probe, never a restart/alternate listener.
    var reservation = new TcpListener(IPAddress.Loopback, 0); reservation.Start();
    var port = ((IPEndPoint)reservation.LocalEndpoint).Port; reservation.Stop();
    var uri = new Uri("ws://127.0.0.1:" + port + "/");
    var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    var verifier = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(token)));
    var start = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true,
        WorkingDirectory = state, RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = true };
    foreach (var key in start.Environment.Keys.Where(k => k.StartsWith("OPENAI_", StringComparison.OrdinalIgnoreCase) ||
        k.StartsWith("ANTHROPIC_", StringComparison.OrdinalIgnoreCase) || k.StartsWith("CLAUDE_", StringComparison.OrdinalIgnoreCase) ||
        k.StartsWith("CODEX_", StringComparison.OrdinalIgnoreCase) || k.StartsWith("CCRELAY_", StringComparison.OrdinalIgnoreCase) ||
        k.StartsWith("AWS_", StringComparison.OrdinalIgnoreCase) || k is "GH_TOKEN" or "GITHUB_TOKEN").ToArray()) start.Environment.Remove(key);
    // Child-only isolation, NOT a production authentication fallback. Never
    // populate this home from the owner home or enter a login/API-key flow.
    start.Environment["CODEX_HOME"] = freshHome;
    foreach (var arg in new[] { "-c", "cli_auth_credentials_store=\"file\"", "app-server", "--listen", uri.ToString().TrimEnd('/'),
        "--ws-auth", "capability-token", "--ws-token-sha256", verifier }) start.ArgumentList.Add(arg);
    stage = "native-start";
    child = Process.Start(start) ?? throw new IOException("Native process did not start");
    output = child.StandardOutput.ReadToEndAsync(); error = child.StandardError.ReadToEndAsync();
    child.StandardInput.Close(); report["nativePid"] = child.Id; report["nativeStartedAt"] = child.StartTime.ToUniversalTime();
    using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60));
    // Read-only readiness polls, not retries of initialize, authentication,
    // enrollment, thread/model actions or an uncertain effect.
    stage = "listener-readiness";
    using (var http = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false }))
    {
        using var ready = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token); ready.CancelAfter(TimeSpan.FromSeconds(15));
        while (true)
        {
            if (child.HasExited) throw new IOException("Native server exited before readiness");
            try
            {
                using var response = await http.GetAsync("http://127.0.0.1:" + port + "/readyz", ready.Token);
                if (response.StatusCode == HttpStatusCode.OK) break;
            }
            catch (HttpRequestException) { }
            await Task.Delay(100, ready.Token);
        }
    }
    stage = "authentication-rejection";
    report["missingBearerRejected"] = await Rpc.Rejected(uri, null, deadline.Token);
    report["wrongBearerRejected"] = await Rpc.Rejected(uri, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)), deadline.Token);
    stage = "two-client-sharing";
    using var first = new Rpc(); using var second = new Rpc();
    await first.Connect(uri, token, deadline.Token); await second.Connect(uri, token, deadline.Token);
    await first.Initialize("oracova_sharing_probe_a", deadline.Token); await second.Initialize("oracova_sharing_probe_b", deadline.Token);
    var identities = new List<string>();
    foreach (var client in new[] { first, second })
    {
        var account = await client.Call("account/read", new { refreshToken = false }, deadline.Token);
        if (account.GetProperty("account").ValueKind != JsonValueKind.Null) throw new InvalidDataException("Probe unexpectedly authenticated");
        var remote = await client.Call("remoteControl/status/read", new { }, deadline.Token);
        if (remote.GetProperty("status").GetString() != "disabled") throw new InvalidDataException("Probe unexpectedly enrolled remote control");
        var installation = remote.GetProperty("installationId").GetString();
        if (string.IsNullOrWhiteSpace(installation)) throw new InvalidDataException("Missing native installation identity");
        identities.Add(Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(installation))));
        var loaded = await client.Call("thread/loaded/list", new { }, deadline.Token);
        if (loaded.GetProperty("data").GetArrayLength() != 0) throw new InvalidDataException("Unexpected loaded thread in isolated probe");
    }
    if (identities[0] != identities[1] || child.HasExited) throw new InvalidDataException("Clients do not share one live native installation");
    report["sharedInstallationFingerprint"] = identities[0]; report["authenticatedLocalClients"] = 2;
    report["nativeAccountAbsent"] = true; report["nativeRemoteState"] = "disabled";
    report["complete"] = true;
}
catch (Exception failure)
{
    // Never print exceptions/argv/responses containing bearer credentials or
    // native metadata. A failure does not authorize replay or login fallback.
    report["failureStage"] = stage; report["errorType"] = failure.GetType().Name;
    Environment.ExitCode = 1;
}
finally
{
    if (child != null)
    {
        // Only this diagnostic's owned process. Existing native remotes and
        // Khadang are never discovered, stopped or restarted by this probe.
        if (!child.HasExited) child.Kill(entireProcessTree: true);
        await child.WaitForExitAsync(); report["ownedNativeExited"] = child.HasExited;
        if (state != null && output != null && error != null)
        {
            File.WriteAllText(Path.Combine(state, "stdout.private"), await output);
            File.WriteAllText(Path.Combine(state, "stderr.private"), await error);
        }
        child.Dispose();
    }
    report["at"] = DateTimeOffset.UtcNow;
    if (state != null) File.WriteAllText(Path.Combine(state, "result.json"), JsonSerializer.Serialize(report));
    Console.WriteLine(JsonSerializer.Serialize(report));
}

sealed class Rpc : IDisposable
{
    private readonly ClientWebSocket socket = new();
    private int next;
    public static void Allowed(string method)
    {
        if (method is not ("initialize" or "account/read" or "remoteControl/status/read" or "thread/loaded/list"))
            throw new InvalidDataException("Mutation is outside transport-probe scope");
    }
    public Task Connect(Uri uri, string token, CancellationToken stop)
    { socket.Options.Proxy = null; socket.Options.SetRequestHeader("Authorization", "Bearer " + token); return socket.ConnectAsync(uri, stop); }
    public async Task Initialize(string name, CancellationToken stop)
    {
        await Call("initialize", new { clientInfo = new { name, version = "1" }, capabilities = new { experimentalApi = true } }, stop);
        await Send(new { method = "initialized" }, stop);
    }
    private Task Send(object message, CancellationToken stop) => socket.SendAsync(new ArraySegment<byte>(JsonSerializer.SerializeToUtf8Bytes(message)), WebSocketMessageType.Text, true, stop);
    public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop)
    {
        Allowed(method); var id = ++next;
        await Send(new { id, method, @params = parameters }, stop);
        for (var messages = 0; messages < 100; messages++)
        {
            using var data = new MemoryStream(); var buffer = new byte[8192]; WebSocketReceiveResult frame;
            do
            {
                frame = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), stop);
                if (frame.MessageType != WebSocketMessageType.Text || data.Length + frame.Count > 65536) throw new InvalidDataException("Unexpected native frame");
                data.Write(buffer, 0, frame.Count);
            } while (!frame.EndOfMessage);
            using var document = JsonDocument.Parse(data.ToArray()); var reply = document.RootElement;
            if (reply.TryGetProperty("method", out _))
            { if (reply.TryGetProperty("id", out _)) throw new InvalidDataException("Unexpected server request"); continue; }
            if (reply.GetProperty("id").GetInt32() != id || reply.TryGetProperty("error", out _)) throw new InvalidDataException("Native read rejected or wrong receipt");
            return reply.GetProperty("result").Clone();
        }
        throw new InvalidDataException("Native notification bound exceeded");
    }
    public static async Task<bool> Rejected(Uri uri, string? token, CancellationToken stop)
    {
        using var denied = new ClientWebSocket(); denied.Options.Proxy = null;
        if (token != null) denied.Options.SetRequestHeader("Authorization", "Bearer " + token);
        denied.Options.CollectHttpResponseDetails = true;
        try { await denied.ConnectAsync(uri, stop); }
        catch (WebSocketException) when (denied.HttpStatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden) { return true; }
        throw new InvalidDataException("Bearer denial was not proven by HTTP 401/403");
    }
    public void Dispose() { socket.Abort(); socket.Dispose(); }
}
