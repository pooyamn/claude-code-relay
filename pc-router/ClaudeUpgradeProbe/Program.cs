using System.Diagnostics;
using System.Security.Principal;
using System.Text.Json;
using KhadangRouter;

// One reviewed owner-requested runtime acceptance, no polling or work replay.
const string root = @"C:\ProgramData\KhadangRouter\release-claude-fable-20261109";
const string pin = "8cd2d34c-0805-4705-8197-d11de0728499";
const string model = "claude-fable-5-2";
var report = new Dictionary<string, object?> { ["complete"] = false, ["modelPromptsAttempted"] = 0 };
try
{
    if (!OperatingSystem.IsWindows() || !WindowsIdentity.GetCurrent().IsSystem || Process.GetCurrentProcess().SessionId != 0)
        throw new UnauthorizedAccessException("Protected SYSTEM checker required; native process remains ordinary owner");
    using var claim = new FileStream(root + @"\native-probe.claim", FileMode.CreateNew, FileAccess.Write, FileShare.None);
    var policy = RouterPolicy.Load(@"C:\ProgramData\KhadangRouter\config.json");
    var binding = new Binding(-1003550185469, 14439, "Motorcontrol Plant", "/Users/pouya/.openclaw/workspace/motorcontrol-plant", pin, "claude", "linux");
    if (policy.LinuxClaude?.Checkpoints[pin].Model != model) throw new InvalidDataException("Exact owner model required");
    using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(150));
    using var ledger = new Ledger(root + @"\native-probe.db");
    var channel = await LinuxClaudeChannel.Open(policy, binding, stop.Token);
    report["observation"] = channel.Observation;
    await using var native = new ClaudeNativeStream(channel, ledger, pin);
    string? actualModel = null, tool = null; bool owner = false;
    var result = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
    native.Notification += frame => {
        try
        {
            var kind = frame.GetProperty("type").GetString();
            if (kind == "assistant" && frame.TryGetProperty("message", out var message))
            {
                if (message.TryGetProperty("model", out var m)) actualModel = m.GetString();
                if (message.TryGetProperty("content", out var blocks) && blocks.ValueKind == JsonValueKind.Array)
                    foreach (var block in blocks.EnumerateArray())
                        if (block.GetProperty("type").GetString() == "tool_use")
                        {
                            if (block.GetProperty("name").GetString() != "Bash" || block.GetProperty("input").GetProperty("command").GetString() != "id -u")
                                throw new InvalidDataException("Unexpected tool in fixed acceptance");
                            tool = block.GetProperty("id").GetString();
                        }
            }
            if (kind == "user" && frame.TryGetProperty("tool_use_result", out var tr) && tr.TryGetProperty("stdout", out var stdout))
                owner = stdout.GetString()?.Trim() == "1000";
            if (kind == "user" && frame.TryGetProperty("message", out var user) && user.TryGetProperty("content", out var content) && content.ValueKind == JsonValueKind.Array)
                foreach (var block in content.EnumerateArray())
                    if (block.GetProperty("type").GetString() == "tool_result" && block.GetProperty("tool_use_id").GetString() == tool &&
                        block.TryGetProperty("content", out var text) && text.ValueKind == JsonValueKind.String && text.GetString()?.Trim() == "1000") owner = true;
            if (kind == "result") result.TrySetResult(frame.Clone());
        }
        catch (Exception error) { result.TrySetException(error); }
    };
    var initialized = await native.Initialize(stop.Token);
    if (initialized.GetProperty("session_state").GetString() != "idle" ||
        !initialized.GetProperty("models").EnumerateArray().Any(m => m.GetProperty("value").GetString() is model or "fable"))
        throw new InvalidDataException("Exact idle saved session and Fable 5.2 catalog entry required");
    report["catalogVerified"] = true;
    report["modelPromptsAttempted"] = 1;
    var receipt = await native.SendNow(pin, JsonSerializer.SerializeToElement("Owner-requested runtime/model restart validation only. Do not resume project work, edit files, delegate, or perform external actions. Use Bash exactly once with exactly `id -u`, then reply exactly MOTOR_FABLE52_READY. This is a read-only acceptance check; await Pouya afterward."), stop.Token);
    report["nativeInputUuid"] = receipt.GetProperty("uuid").GetString();
    var final = await result.Task.WaitAsync(stop.Token);
    report["actualModel"] = actualModel; report["toolOwnerUid1000"] = owner;
    if (actualModel != model || !owner || tool == null || final.GetProperty("is_error").GetBoolean() ||
        final.GetProperty("result").GetString()?.Trim() != "MOTOR_FABLE52_READY" || ledger.Unknown != 0)
        throw new InvalidDataException("Actual Fable response, ordinary tool UID and settled native receipt required");
    report["complete"] = true; report["continuityVerified"] = true;
}
catch (Exception error)
{
    report["failureType"] = error.GetType().Name;
    File.WriteAllText(root + @"\native-probe-failure.private.txt", error.ToString());
    Environment.ExitCode = 1;
}
finally
{
    report["at"] = DateTimeOffset.UtcNow;
    File.WriteAllText(root + @"\native-probe.json", JsonSerializer.Serialize(report));
}
