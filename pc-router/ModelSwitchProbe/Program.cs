using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using KhadangRouter;

// Candidate-bound SYSTEM checker, not a poller. The actual Claude processes
// still use the attested ordinary owner. It does not touch live bindings.
string? state = null;
var report = new Dictionary<string, object?> { ["complete"] = false, ["routingChanged"] = false, ["modelPromptsAttempted"] = 0 };
try
{
    if (!OperatingSystem.IsWindows() || args.Length != 2 || !Guid.TryParseExact(args[0], "N", out _) ||
        args[1].Length != 64 || !args[1].All(Uri.IsHexDigit)) throw new InvalidDataException("Exact generation and candidate digest required");
    using var identity = WindowsIdentity.GetCurrent();
    if (!identity.IsSystem || Process.GetCurrentProcess().SessionId != 0 || Environment.MachineName != "DESKTOP-8SO9HDK")
        throw new InvalidDataException("Protected SYSTEM checker required");
    state = @"C:\ProgramData\KhadangRouter\release-" + args[0] + @"\handoff-proof";
    using var claim = new FileStream(state + @"\one-shot.claim", FileMode.CreateNew, FileAccess.Write, FileShare.None);
    var digest = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(Router).Assembly.Location)));
    if (!digest.Equals(args[1], StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Candidate assembly changed");
    var policy = RouterPolicy.Load(state + @"\candidate.json");
    var bindings = JsonSerializer.Deserialize<Binding[]>(File.ReadAllText(state + @"\bindings.json"))!;
    var source = bindings.Single(b => b.Chat == -1003550185469 && b.Topic == 816);
    if (source.ThreadId != "01a0facd-1bc0-7d23-95d6-c32fde0c62db" || source.Workspace != "/Users/pouya/.openclaw/workspace/claude-code-relay" ||
        source.Runtime != "linux" || source.Backend != "codex" || policy.OwnerFullAccess)
        throw new InvalidDataException("Fixed read-only test scope required");
    var target = source with { Backend = "claude", ThreadId = Guid.NewGuid().ToString("D") };
    var marker = "CCRELAY_HANDOFF_READY_" + args[0];
    using var ledger = new Ledger(state + @"\proof.db");
    ledger.Put("model-slot/" + target.Chat + "/" + target.Topic + "/claude", target);
    report["routerSha256"] = digest; report["policySha256"] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(state + @"\candidate.json")));
    report["binding"] = target;
    var observations = new List<LinuxClaudeObservation>();
    using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(150));
    for (int attempt = 0; attempt < 2; attempt++)
    {
        var factory = new LinuxClaudeTopics(policy, ledger, bindings);
        await using var client = await factory.OpenForSwitch(source, target, attempt == 0, "haiku", stop.Token);
        var channel = (LinuxClaudeChannel)typeof(ClaudeNativeStream).GetField("channel", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(client)!;
        observations.Add(channel.Observation);
        var result = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        var idle = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        bool completed = false, uidObserved = false;
        client.Notification += frame => {
            try
            {
                var kind = frame.GetProperty("type").GetString();
                if (kind == "control_request") throw new InvalidDataException("Unexpected approval/question; never automatically answer");
                if (kind is "assistant" or "user" && frame.TryGetProperty("message", out var message) && message.TryGetProperty("content", out var blocks) && blocks.ValueKind == JsonValueKind.Array)
                    foreach (var block in blocks.EnumerateArray())
                    {
                        var type = block.GetProperty("type").GetString();
                        if (type == "tool_use" && (attempt != 0 || block.GetProperty("name").GetString() != "Bash" || block.GetProperty("input").GetProperty("command").GetString() != "id -u"))
                            throw new InvalidDataException("Unexpected canary tool use");
                        if (type == "tool_result" && block.TryGetProperty("content", out var content) && content.ValueKind == JsonValueKind.String && content.GetString()!.Trim() == "1000") uidObserved = true;
                    }
                if (kind == "result") { completed = true; result.TrySetResult(frame.Clone()); }
                if (completed && kind == "system" && frame.TryGetProperty("subtype", out var sub) && sub.GetString() == "session_state_changed" && frame.GetProperty("state").GetString() == "idle") idle.TrySetResult();
            }
            catch (Exception error) { result.TrySetException(error); idle.TrySetException(error); }
        };
        var initialized = await client.Initialize(stop.Token);
        if (initialized.GetProperty("session_state").GetString() != "idle") throw new InvalidDataException("Canary must initialize idle");
        var prompt = attempt == 0 ? "Owner-authorized PC handoff canary only. Do not read files, change anything, delegate or perform external actions. " +
            "Use Bash exactly once with the command id -u. Verify it returned 1000. Then reply exactly " + marker + "." :
            "Handoff continuity check only. Without using tools or performing any actions, reply with the exact CCRELAY_HANDOFF_READY marker from the previous turn.";
        report["modelPromptsAttempted"] = attempt + 1;
        File.WriteAllText(state + @"\intent.json", JsonSerializer.Serialize(report));
        await client.SendNow(target.ThreadId, JsonSerializer.SerializeToElement(prompt), stop.Token);
        var final = await result.Task.WaitAsync(stop.Token);
        if (final.GetProperty("subtype").GetString() != "success" || final.GetProperty("result").GetString()!.Trim() != marker || attempt == 0 && !uidObserved)
            throw new InvalidDataException("Canary did not prove exact marker/tool owner");
        await idle.Task.WaitAsync(stop.Token);
        if (ledger.Unknown != 0) throw new InvalidDataException("Canary delivery uncertain; no automatic retry");
    }
    if (observations[0].NativeGeneration == observations[1].NativeGeneration || observations.Any(o => o.WindowsOwner.Elevated || o.WindowsOwner.Session <= 0 || o.SessionId != target.ThreadId))
        throw new InvalidDataException("Independent same-ID ordinary-owner generations required");
    report["observations"] = observations; report["nativeLinuxClaudeLaunchVerified"] = true;
    report["nativeLinuxClaudeToolOwnerVerified"] = true; report["nativeLinuxClaudeContinuityVerified"] = true;
    report["complete"] = true;
}
catch (Exception error)
{
    report["failureType"] = error.GetType().Name;
    if (state != null && Directory.Exists(state)) File.WriteAllText(state + @"\failure.private.txt", error.ToString());
    Environment.ExitCode = 1;
}
finally
{
    if (state != null && Directory.Exists(state)) { report["at"] = DateTimeOffset.UtcNow; File.WriteAllText(state + @"\result.json", JsonSerializer.Serialize(report)); }
}
