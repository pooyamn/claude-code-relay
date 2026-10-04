using System.Diagnostics;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using KhadangRouter;

// A fixed personal migration check, not a new role/broker or live poller.
// Each attempt owns one exact retained PC conversation and private journal.
// Run the continuation mode only against a newly reviewed transcript checkpoint.
const string session = "7dc840b0-402f-451e-bc79-dadfb706d363";
const string workspace = "/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts";
const string routerDigest = "84AB5DEA4B368980A0754FB64D23F2ABBE0F63DCADA6EAFDB1F752E1A37E5690";
const string handoffDigest = "e639f198591c5326702d3bd9bd568397c6bce1eac86029ddbfb513e1563bdce7";
const string marker = "DUT_PC_CLAUDE_HANDOFF_READY";
string? state = null;
var report = new Dictionary<string, object?> { ["complete"] = false, ["routingChanged"] = false,
    ["nativeLinuxClaudeLaunchVerified"] = false, ["nativeLinuxClaudeToolOwnerVerified"] = false,
    ["nativeLinuxClaudeContinuityVerified"] = false, ["modelPromptsAttempted"] = 0 };
try
{
    if (args.SequenceEqual(new[] { "--self-test" })) { Evidence.Tests(); return; }
    if (!OperatingSystem.IsWindows() || args.Length != 3 || args[0] is not ("--handoff" or "--continuity") ||
        !Guid.TryParseExact(args[1], "N", out _) || !Guid.TryParseExact(args[2], "N", out _))
        throw new InvalidDataException("Fixed Windows DUT mode, attempt and checkpoint generation required");
    using var identity = WindowsIdentity.GetCurrent();
    if (Environment.MachineName != "DESKTOP-8SO9HDK" || !identity.IsSystem || Process.GetCurrentProcess().SessionId != 0)
        throw new InvalidDataException("Protected SYSTEM checker required; native tools still run as the limited owner");
    state = @"C:\ProgramData\KhadangRouter\dut-claude-acceptance-" + args[1];
    var config = state + @"\candidate.json";
    Protected(config, @"C:\ProgramData\KhadangRouter");
    using var claim = new FileStream(state + @"\one-shot.claim", FileMode.CreateNew, FileAccess.Write, FileShare.None);
    if (Hash(typeof(Router).Assembly.Location) != routerDigest)
        throw new InvalidDataException("Actual reviewed production router assembly required");
    var policy = RouterPolicy.Load(config);
    var binding = new Binding(-1004395661179, 53, "DUT Board Design · PC", workspace, session, "claude", "linux");
    policy.ValidateBindings([binding]);
    var runtime = policy.LinuxClaude ?? throw new InvalidDataException("Exact protected Claude runtime required");
    if (policy.OwnerSid != "S-1-5-21-71459778-1164188569-2276148161-1001" || policy.OwnerId != 110123423 ||
        runtime.PackageRoot != @"C:\ProgramData\OracovaNativeRemote\claude-connector-" + args[2] ||
        runtime.Checkpoints.Count != 1 || !runtime.Checkpoints.TryGetValue(session, out var checkpoint) ||
        checkpoint.Chat != binding.Chat || checkpoint.Topic != binding.Topic || checkpoint.Workspace != workspace)
        throw new InvalidDataException("Exact DUT owner/topic/checkpoint required");
    report["mode"] = args[0]; report["binding"] = binding;
    report["checkpointSha256"] = checkpoint.Sha256; report["handoffSha256"] = handoffDigest;
    report["policySha256"] = Hash(config); report["routerSha256"] = routerDigest;
    using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(150));
    using var ledger = new Ledger(state + @"\acceptance.db");
    ledger.Put("launch", new { checkpoint.Sha256, session, state = "attempted", at = DateTimeOffset.UtcNow });
    var channel = await LinuxClaudeChannel.Open(policy, binding, stop.Token);
    report["observation"] = channel.Observation;
    report["nativeLinuxClaudeLaunchVerified"] = true;
    await using (var client = new ClaudeNativeStream(channel, ledger, session))
    {
        var evidence = new Evidence(args[0] == "--continuity");
        var result = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        var idle = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var completed = false;
        client.Notification += message => {
            try
            {
                evidence.Observe(message);
                if (message.GetProperty("type").GetString() == "result") { completed = true; result.TrySetResult(message); }
                if (completed && message.GetProperty("type").GetString() == "system" &&
                    message.TryGetProperty("subtype", out var subtype) && subtype.GetString() == "session_state_changed" &&
                    message.GetProperty("state").GetString() == "idle") idle.TrySetResult();
            }
            catch (Exception error) { result.TrySetException(error); idle.TrySetException(error); }
        };
        var initialized = await client.Initialize(stop.Token);
        if (initialized.GetProperty("session_state").GetString() != "idle")
            throw new InvalidDataException("Retained DUT must resume idle; never continue an unfinished action automatically");
        var prompt = args[0] == "--handoff"
            ? "PC migration verification only. Do not start DUT X, change files, delegate, or perform external actions. " +
              "Use Read to read all of " + workspace + "/PC-MIGRATION-HANDOFF.md. " +
              "Then use Bash with exactly this command: " + Evidence.Command + ". " +
              "After reading the handoff and verifying UID 1000 and its checksum, reply exactly " + marker + "."
            : "PC migration continuity verification only. Without using any tools or starting project work, " +
              "reply with the exact migration-ready marker from the previous successful verification turn in this conversation.";
        report["modelPromptsAttempted"] = 1; // Durable input journal commits before SendNow writes.
        var receipt = await client.SendNow(session, JsonSerializer.SerializeToElement(prompt), stop.Token);
        report["nativeInputReceipt"] = receipt.GetProperty("uuid").GetString();
        var response = await result.Task.WaitAsync(stop.Token);
        evidence.Complete(response);
        await idle.Task.WaitAsync(stop.Token);
        if (ledger.Unknown != 0) throw new InvalidDataException("Uncertain delivery preserved; do not repeat this prompt");
        report["nativeLinuxClaudeToolOwnerVerified"] = args[0] == "--handoff";
        report["nativeLinuxClaudeContinuityVerified"] = args[0] == "--continuity";
        report["nativeIdleAfterResult"] = true; report["unknownEffects"] = 0;
        report["complete"] = true;
    }
}
catch (Exception error)
{
    report["complete"] = false; report["failureType"] = error.GetType().Name;
    if (state != null && Directory.Exists(state)) File.WriteAllText(state + @"\failure.private.txt", error.ToString());
    Environment.ExitCode = 1;
}
finally
{
    if (state != null && Directory.Exists(state))
    {
        report["at"] = DateTimeOffset.UtcNow;
        File.WriteAllText(state + @"\result.json", JsonSerializer.Serialize(report));
        Console.WriteLine(JsonSerializer.Serialize(report));
    }
}

static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
static void Protected(string path, string root)
{
    if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
    if (!path.StartsWith(root + "\\", StringComparison.Ordinal) || path.Split('\\').Any(p => p is "." or ".."))
        throw new InvalidDataException("Literal protected candidate required");
    for (FileSystemInfo? item = new FileInfo(path); item != null; item = item is FileInfo f ? f.Directory : ((DirectoryInfo)item).Parent)
    {
        if (!item.Exists || (item.Attributes & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("Candidate path cannot redirect");
        var acl = item is FileInfo file ? (FileSystemSecurity)file.GetAccessControl() : ((DirectoryInfo)item).GetAccessControl();
        if (acl.GetOwner(typeof(SecurityIdentifier))?.Value is not ("S-1-5-18" or "S-1-5-32-544"))
            throw new InvalidDataException("Protected candidate owner required");
        const FileSystemRights mutation = FileSystemRights.Write | FileSystemRights.Delete | FileSystemRights.DeleteSubdirectoriesAndFiles |
            FileSystemRights.ChangePermissions | FileSystemRights.TakeOwnership;
        foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            if (rule.AccessControlType == AccessControlType.Allow && (rule.FileSystemRights & mutation) != 0 &&
                rule.IdentityReference.Value is not ("S-1-5-18" or "S-1-5-32-544"))
                throw new InvalidDataException("Owner cannot modify acceptance code or evidence");
        if (item.FullName == root) { if (!acl.AreAccessRulesProtected) throw new InvalidDataException("Protected root required"); break; }
    }
}

sealed class Evidence(bool continuity)
{
    public const string Command = "id -u && sha256sum -- PC-MIGRATION-HANDOFF.md";
    private readonly Dictionary<string, string> calls = new(StringComparer.Ordinal);
    private readonly HashSet<string> results = new(StringComparer.Ordinal);
    public void Observe(JsonElement frame)
    {
        var kind = frame.GetProperty("type").GetString();
        if (kind == "control_request") throw new InvalidDataException("Unexpected native question/permission; preserve instead of answering automatically");
        if (kind is not ("assistant" or "user") || !frame.TryGetProperty("message", out var message) ||
            !message.TryGetProperty("content", out var blocks) || blocks.ValueKind != JsonValueKind.Array) return;
        foreach (var block in blocks.EnumerateArray())
        {
            var type = block.GetProperty("type").GetString();
            if (type == "tool_use")
            {
                var name = block.GetProperty("name").GetString()!;
                var input = block.GetProperty("input");
                if (continuity || name == "Bash" && input.GetProperty("command").GetString() != Command ||
                    name == "Read" && (input.GetProperty("file_path").GetString() !=
                        "/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts/PC-MIGRATION-HANDOFF.md" ||
                        input.TryGetProperty("offset", out _) || input.TryGetProperty("limit", out _)) || name is not ("Read" or "Bash"))
                    throw new InvalidDataException("Unexpected migration tool call");
                if (!calls.TryAdd(block.GetProperty("id").GetString()!, name) || calls.Values.Count(n => n == name) != 1)
                    throw new InvalidDataException("Repeated migration tool use; do not replay");
            }
            if (type == "tool_result")
            {
                var id = block.GetProperty("tool_use_id").GetString()!;
                if (!calls.TryGetValue(id, out var name) || !results.Add(id) ||
                    block.TryGetProperty("is_error", out var error) && error.GetBoolean())
                    throw new InvalidDataException("Unmatched or failed migration tool result");
                var content = block.GetProperty("content");
                var text = content.ValueKind == JsonValueKind.String ? content.GetString()! :
                    string.Join("\n", content.EnumerateArray().Select(b => b.GetProperty("text").GetString()));
                if (name == "Bash" && text.Trim().Replace("\r\n", "\n") !=
                    "1000\ne639f198591c5326702d3bd9bd568397c6bce1eac86029ddbfb513e1563bdce7  PC-MIGRATION-HANDOFF.md" ||
                    name == "Read" && !text.Contains("DUT X", StringComparison.Ordinal))
                    throw new InvalidDataException("Actual tool-owner/handoff evidence mismatch");
            }
        }
    }
    public void Complete(JsonElement response)
    {
        if (response.GetProperty("session_id").GetString() != "7dc840b0-402f-451e-bc79-dadfb706d363" ||
            response.GetProperty("subtype").GetString() != "success" || response.GetProperty("is_error").GetBoolean() ||
            response.GetProperty("result").GetString()!.Trim() != "DUT_PC_CLAUDE_HANDOFF_READY" ||
            !continuity && (calls.Count != 2 || results.Count != 2))
            throw new InvalidDataException("Exact completed DUT checkpoint reply required");
    }
    public static void Tests()
    {
        var result = JsonSerializer.SerializeToElement(new { session_id = "7dc840b0-402f-451e-bc79-dadfb706d363",
            subtype = "success", is_error = false, result = "DUT_PC_CLAUDE_HANDOFF_READY" });
        new Evidence(true).Complete(result);
        void Reject(Action action) { try { action(); } catch (InvalidDataException) { return; } throw new Exception("Unsafe acceptance passed"); }
        Reject(() => new Evidence(false).Complete(result));
        Reject(() => new Evidence(true).Observe(JsonSerializer.SerializeToElement(new { type = "control_request" })));
        var read = JsonSerializer.SerializeToElement(new { type = "assistant", message = new { content = new[] {
            new { type = "tool_use", id = "read", name = "Read", input = new { file_path = "/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts/PC-MIGRATION-HANDOFF.md" } } } } });
        Reject(() => new Evidence(true).Observe(read));
        var evidence = new Evidence(false); evidence.Observe(read); Reject(() => evidence.Observe(read));
        Console.WriteLine("DUT Claude evidence fixtures: 5 passed; not live acceptance");
    }
}
