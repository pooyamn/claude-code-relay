using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using KhadangRouter;

// Fixed, one-shot proof of the candidate's REAL SYSTEM -> limited Windows owner
// -> UID 1000 connector to the already-running, paired native daemon. No bot
// credential decryption, Telegram poll, prompt or daemon lifecycle. Creation
// modes are separately selected, fixed one-shot migration actions: create a fresh thread
// with the reviewed handoff, but never start a model or repeat a prior attempt.
if (args.SequenceEqual(new[] { "--self-test" }))
{
    foreach (var method in new[] { "remoteControl/status/read", "remoteControl/client/list", "thread/loaded/list" }) Allowed(method);
    foreach (var method in new[] { "turn/start", "turn/steer", "thread/resume", "thread/start", "remoteControl/enable", "command/exec" })
    {
        try { Allowed(method); throw new InvalidOperationException("Unsafe observation accepted"); }
        catch (InvalidDataException) { }
    }
    const string saved = "{\"type\":\"session_meta\",\"payload\":{\"id\":\"test-thread\"}}\n" +
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"exact checkpoint\"}]}}";
    if (!CheckpointPersisted(saved, "test-thread", "exact checkpoint") || CheckpointPersisted(saved, "test-thread", "checkpoint") ||
        CheckpointPersisted(saved, "other-thread", "exact checkpoint") ||
        CheckpointPersisted(saved.Replace("\"user\"", "\"assistant\""), "test-thread", "exact checkpoint"))
        throw new InvalidOperationException("Exact raw checkpoint verification failed");
    var web = Target("--create-web")!; var board = Target("--create-base")!; var marginal = Target("--create-marginal")!;
    if (Target("--run") != null || Target("--unknown") != null || web.Topic != 8660 || web.Chat != -1003550185469 ||
        board.Topic != 18 || marginal.Topic != 427 || board.Chat != -1004395661179 || marginal.Chat != board.Chat ||
        board.Workspace != LinuxCodexRuntime.WorkspaceRoot + "/ai-hil/hardware/augur-1" ||
        marginal.Workspace != LinuxCodexRuntime.WorkspaceRoot + "/marginal-requests" ||
        new[] { web, board, marginal }.Select(t => t.SourceThread).Distinct().Count() != 3 ||
        new[] { web, board, marginal }.Any(t => t.Model != "gpt-6-astra" || t.HandoffSha256.Length != 64))
        throw new InvalidOperationException("Fixed source-topic creation targets differ");
    Console.WriteLine("Managed connector observation guards passed; no native activity.");
    return;
}
string? root = null;
var target = args.Length == 2 ? Target(args[0]) : null;
var report = new Dictionary<string, object?> { ["complete"] = false, ["modelsStarted"] = false,
    ["productionChanged"] = false, ["existingConversationsResumed"] = false, ["telegramPolling"] = false };
try
{
    if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
    using var identity = WindowsIdentity.GetCurrent();
    if (Environment.MachineName != "DESKTOP-8SO9HDK" || !identity.IsSystem ||
        Process.GetCurrentProcess().SessionId != 0 || args.Length != 2 || args[0] is not ("--run" or "--create-web" or "--create-base" or "--create-marginal") || !Guid.TryParseExact(args[1], "N", out var run))
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
    var binding = new Binding(policy.ChatId, 159, "Observation only", target?.Workspace ?? LinuxCodexRuntime.WorkspaceRoot + "/ai-hil/web", "observation-only", "codex", "linux");
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
    if (target != null)
    {
        // A pre-creation observation of zero cannot describe later mutations
        // if an exception prevents their final reconciliation.
        report["unknownEffects"] = null;
        var expectedHandoff = target.HandoffSha256;
        var file = binding.Workspace + "/PC-MIGRATION-HANDOFF.md";
        var checkpoint = await rpc.Call("command/exec", new { command = new[] { "/usr/bin/cat", file },
            cwd = binding.Workspace, sandboxPolicy = new { type = "dangerFullAccess" }, timeoutMs = 10000 }, stop.Token);
        var handoff = checkpoint.GetProperty("stdout").GetString()!;
        if (checkpoint.GetProperty("exitCode").GetInt32() != 0 ||
            Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(handoff))).ToLowerInvariant() != expectedHandoff)
            throw new InvalidDataException("Project handoff bytes differ from reviewed source; no new thread");
        var context = "[Migration checkpoint; not a request to start work.] Pouya approved a fresh PC session for this existing topic. " +
            "Load the following reviewed handoff. Do not replay previous actions or start a goal; wait for the next owner input. " +
            "Handoff SHA-256: " + expectedHandoff + "\n\n" + handoff;
        var started = await rpc.Call("thread/start", new { cwd = binding.Workspace, model = target.Model,
            approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", permissions = policy.NativePermissionProfile,
            allowProviderModelFallback = false }, stop.Token);
        var thread = started.GetProperty("thread").GetProperty("id").GetString()!;
        if (!Guid.TryParseExact(thread, "D", out _) || thread == target.SourceThread ||
            started.GetProperty("cwd").GetString() != binding.Workspace || started.GetProperty("model").GetString() != target.Model)
            throw new InvalidDataException("Created native session does not match the explicit fresh project migration");
        // Save the new identity BEFORE the next effect. A partial attempt is
        // retained for reconciliation, never replaced with another fresh thread.
        var migrated = new Binding(target.Chat, target.Topic, target.Name + " · PC", binding.Workspace, thread, "codex", "linux");
        File.WriteAllText(Path.Combine(state, "created-native-thread.json"), JsonSerializer.Serialize(new {
            binding = migrated, model = target.Model, sourceThread = target.SourceThread, handoffSha256 = expectedHandoff, at = DateTimeOffset.UtcNow }));
        report["newPcBinding"] = migrated;
        await rpc.Call("thread/inject_items", new { threadId = thread, items = new[] { new { type = "message", role = "user",
            content = new[] { new { type = "input_text", text = context } } } } }, stop.Token);
        await rpc.Call("thread/name/set", new { threadId = thread, name = target.Name + " (topic " + target.Topic + ") · PC" }, stop.Token);
        var persisted = await rpc.Call("thread/read", new { threadId = thread, includeTurns = true }, stop.Token, effect: false);
        var storedThread = persisted.GetProperty("thread");
        var path = storedThread.GetProperty("path").GetString()!;
        if (storedThread.GetProperty("id").GetString() != thread ||
            !path.StartsWith("/Users/pouya/.codex/sessions/", StringComparison.Ordinal) ||
            !path.EndsWith("-" + thread + ".jsonl", StringComparison.Ordinal) || path.Contains("..") || path.Any(char.IsControl))
            throw new InvalidDataException("Exact new session storage identity did not persist; preserve this attempt");
        // inject_items persists raw Responses items without making a turn. In
        // Codex 0.160.0 thread/read's normal turns omit those raw-only items.
        // Verify the exact user checkpoint in the exact native rollout instead
        // of rejecting a successful injection or replaying it into a new turn.
        var raw = await rpc.Call("command/exec", new { command = new[] { "/usr/bin/cat", path },
            cwd = binding.Workspace, sandboxPolicy = new { type = "dangerFullAccess" }, timeoutMs = 10000 }, stop.Token);
        if (raw.GetProperty("exitCode").GetInt32() != 0 || !CheckpointPersisted(raw.GetProperty("stdout").GetString()!, thread, context))
            throw new InvalidDataException("Exact raw session checkpoint did not persist; preserve this attempt");
        if (ledger.Unknown != 0) throw new InvalidDataException("Uncertain migration outcome; do not replay");
        report["unknownEffects"] = 0;
        report["freshSessionCreated"] = true; report["handoffPersistedAndReadBack"] = true;
        report["handoffSha256"] = expectedHandoff;
    }
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
static bool CheckpointPersisted(string jsonl, string thread, string expected)
{
    if (jsonl.Length > 2_000_000) throw new InvalidDataException("New checkpoint rollout exceeds bound");
    bool identity = false, checkpoint = false;
    foreach (var line in jsonl.Split('\n', StringSplitOptions.RemoveEmptyEntries))
    {
        using var doc = JsonDocument.Parse(line); var item = doc.RootElement;
        var kind = item.GetProperty("type").GetString(); var payload = item.GetProperty("payload");
        if (kind == "session_meta")
        {
            if (payload.GetProperty("id").GetString() != thread) return false;
            identity = true;
        }
        if (kind != "response_item" || !payload.TryGetProperty("type", out var type) || type.GetString() != "message" ||
            !payload.TryGetProperty("role", out var role) || role.GetString() != "user" ||
            !payload.TryGetProperty("content", out var content) || content.ValueKind != JsonValueKind.Array) continue;
        checkpoint |= content.EnumerateArray().Any(part => part.TryGetProperty("type", out var contentType) &&
            contentType.GetString() == "input_text" && part.TryGetProperty("text", out var text) && text.GetString() == expected);
    }
    return identity && checkpoint;
}
static MigrationTarget? Target(string mode) => mode switch
{
    "--create-web" => new(-1003550185469, 8660, "Web", LinuxCodexRuntime.WorkspaceRoot + "/ai-hil/web", "gpt-6-astra",
        "01a0ee66-b1e1-75b1-8a15-eb2e5175f6dd", "d6fe808e29a4ea5854eada96de66c7469ed8e5028c736304f7c03ebe51bda1dd"),
    "--create-base" => new(-1004395661179, 18, "Base board", LinuxCodexRuntime.WorkspaceRoot + "/ai-hil/hardware/augur-1", "gpt-6-astra",
        "01a091ea-58ec-7c20-b238-b3bef0af437b", "dde3218bb6bad93d10f1ee1c82e56230a6930eb0dc9cd6d4cee4249890ed2193"),
    "--create-marginal" => new(-1004395661179, 427, "Marginal Requests", LinuxCodexRuntime.WorkspaceRoot + "/marginal-requests", "gpt-6-astra",
        "01a0c4c2-ea71-7c10-9a39-6440ce5e4a02", "95d990989cd907fb8c1a70354aa0634ad35b43229a7f4913a7d96604157efce7"),
    _ => null
};
sealed record MigrationTarget(long Chat, int Topic, string Name, string Workspace, string Model, string SourceThread, string HandoffSha256);
