using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using KhadangRouter;

// Fixed, one-shot proof of the candidate's REAL SYSTEM -> limited Windows owner
// -> UID 1000 connector to the already-running, paired native daemon. No bot
// credential decryption, Telegram poll, thread resume/start, prompt or lifecycle.
if (args.SequenceEqual(new[] { "--self-test" }))
{
    foreach (var method in new[] { "remoteControl/status/read", "remoteControl/client/list", "thread/loaded/list" }) Allowed(method);
    foreach (var method in new[] { "turn/start", "turn/steer", "thread/resume", "thread/start", "remoteControl/enable", "command/exec" })
    {
        try { Allowed(method); throw new InvalidOperationException("Unsafe observation accepted"); }
        catch (InvalidDataException) { }
    }
    Console.WriteLine("Managed connector observation guards passed; no native activity.");
    return;
}
string? root = null;
var report = new Dictionary<string, object?> { ["complete"] = false, ["modelsStarted"] = false,
    ["productionChanged"] = false, ["existingConversationsResumed"] = false, ["telegramPolling"] = false };
try
{
    if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
    using var identity = WindowsIdentity.GetCurrent();
    if (Environment.MachineName != "DESKTOP-8SO9HDK" || !identity.IsSystem ||
        Process.GetCurrentProcess().SessionId != 0 || args.Length != 2 || args[0] != "--run" || !Guid.TryParseExact(args[1], "N", out var run))
        throw new InvalidDataException("Exact fixed SYSTEM diagnostic task required; native remains ordinary owner");
    root = LinuxCodexRuntime.ProtectedRoot + "\\codex-connector-" + run.ToString("N");
    var state = Path.Combine(root, "proof");
    if (Directory.Exists(state) || File.Exists(state)) throw new InvalidDataException("Prior attempt retained; no replay");
    Directory.CreateDirectory(state);
    using var claim = new FileStream(Path.Combine(state, "one-shot.claim"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
    var config = Path.Combine(root, "reviewed-policy.json");
    var policy = RouterPolicy.Load(config);
    if (policy.StateDirectory != state || policy.LinuxCodex?.PackageRoot != root)
        throw new InvalidDataException("Policy does not match the fixed diagnostic release");
    var binding = new Binding(policy.ChatId, 159, "Observation only", LinuxCodexRuntime.WorkspaceRoot + "/ai-hil/web", "observation-only", "codex", "linux");
    using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(60));
    using var ledger = new Ledger(Path.Combine(state, "observation.db"));
    var connected = await LinuxCodexChannel.ConnectVerified(policy, [binding], ledger, stop.Token);
    await using var rpc = connected.Rpc;
    report["observation"] = connected.Observation;
    var remote = await Read(rpc, "remoteControl/status/read", stop.Token);
    var environment = remote.GetProperty("environmentId").GetString();
    var fingerprint = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(environment ?? ""))).ToLowerInvariant();
    if (remote.GetProperty("status").GetString() != "connected" ||
        fingerprint != "411f13f2b5008f9b1d9be1f4a6900aa2e435f21bd7bb076c490b6cb57622cdfa")
        throw new InvalidDataException("Connector is not observing the connected distinct PC host");
    report["remoteState"] = "connected"; report["environmentFingerprint"] = fingerprint;
    var clients = await Read(rpc, "remoteControl/client/list", stop.Token, new { environmentId = environment, limit = 20 });
    var loaded = await Read(rpc, "thread/loaded/list", stop.Token);
    var data = clients.TryGetProperty("data", out var list) ? list : clients.GetProperty("clients");
    report["registeredClientCount"] = data.GetArrayLength();
    report["loadedThreadCount"] = loaded.GetProperty("data").GetArrayLength();
    report["nativeAccountAndToolUidVerified"] = true; // ConnectVerified checks ChatGPT account and fixed id -u.
    report["credentialReadDenied"] = true; // Exact OS denial is part of connector/launcher attestation.
    report["unknownEffects"] = ledger.Unknown;
    report["routerSha256"] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(Router).Assembly.Location)));
    report["policySha256"] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(config)));
    if (ledger.Unknown != 0) throw new InvalidDataException("Unexpected uncertain observation outcome");
    report["complete"] = true;
}
catch (Exception error)
{
    report["complete"] = false; report["failureType"] = error.GetType().Name;
    if (root != null && Directory.Exists(Path.Combine(root, "proof")))
        File.WriteAllText(Path.Combine(root, "proof", "failure.private.txt"), error.ToString());
    Environment.ExitCode = 1;
}
finally
{
    report["at"] = DateTimeOffset.UtcNow;
    if (root != null && Directory.Exists(Path.Combine(root, "proof")))
        File.WriteAllText(Path.Combine(root, "proof", "result.json"), JsonSerializer.Serialize(report));
    Console.WriteLine(JsonSerializer.Serialize(report));
}
static void Allowed(string method)
{
    if (method is not ("remoteControl/status/read" or "remoteControl/client/list" or "thread/loaded/list"))
        throw new InvalidDataException("Only native observation requests are allowed");
}
static Task<JsonElement> Read(NativeRpc rpc, string method, CancellationToken stop, object? parameters = null)
{
    Allowed(method); return rpc.Call(method, parameters ?? new { }, stop, effect: false);
}
