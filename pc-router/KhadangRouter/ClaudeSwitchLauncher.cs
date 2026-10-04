using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

// The SYSTEM owner-command path creates/checkpoints only an already-registered
// topic in its unchanged workspace. Worker input cannot select code, accounts,
// secret paths, WSL identities, daemon sockets, policy or deployment actions.
public sealed partial class LinuxClaudeTopics
{
    private readonly RouterPolicy policy;
    private string CheckpointKey(Binding b) => "claude/switch-checkpoint/" + b.ThreadId;
    public async Task<IClaudeNative> OpenForSwitch(Binding source, Binding target, bool fresh, string? model, CancellationToken stop)
    {
        if (runtime == null || !selected.TryGetValue(source.Address, out var enrolled) || enrolled.Workspace != source.Workspace ||
            source.Address != target.Address || source.Workspace != target.Workspace || source.Runtime != "linux" || target.Runtime != "linux" ||
            target.Backend != "claude" || !LinuxClaudeRuntime.Session(target.ThreadId) || ledger.Unknown != 0 ||
            ledger.Get(ModelCommand.Slot(target.Address, "claude")) is not { } slot || JsonSerializer.Deserialize<Binding>(slot.GetRawText()) != target)
            throw new InvalidDataException("Exact protected owner topic-switch enrollment required");
        policy.ValidateBindings([target]);
        if (model != null && !System.Text.RegularExpressions.Regex.IsMatch(model, @"\A[A-Za-z0-9][A-Za-z0-9._\[\]-]*\z")) throw new InvalidDataException("Literal native model required");
        var path = runtime.PackageRoot + "\\handoff-" + target.ThreadId + ".json";
        string digest;
        if (fresh)
        {
            if (File.Exists(path) || ledger.Get(CheckpointKey(target)) != null) throw new InvalidOperationException("Claude creation was already attempted; do not create or replay another session");
            digest = WriteCheckpoint(path, new { schema = "ccrelay.personal_claude_start.v1", session_id = target.ThreadId,
                workspace = target.Workspace, source_writer = "owner_switch", uncertain_actions = Array.Empty<string>(),
                history = (object?)null, profile = "/Users/pouya/.claude" }, create: true);
        }
        else
        {
            var prior = ledger.Get(CheckpointKey(target));
            if (prior is { } saved)
            {
                if (saved.GetProperty("binding").Deserialize<Binding>() != target) throw new InvalidDataException("Claude checkpoint belongs to another binding");
                digest = saved.GetProperty("sha256").GetString()!;
                if (model == null && saved.TryGetProperty("model", out var selectedModel)) model = selectedModel.GetString();
            }
            else digest = runtime.For(target).Sha256;
            var oldRuntime = For(target, digest);
            using var process = WindowsOwnerProcess.StartLinuxClaude(policy with { LinuxClaude = oldRuntime }, policy.WorkspaceRoot + "\\lg-magic", target, snapshot: true);
            var owner = process.ObserveOwner(); LinuxClaudeChannel.ValidateOwner(owner, policy.OwnerSid);
            var line = await process.Output.ReadLineAsync(stop).AsTask().WaitAsync(TimeSpan.FromSeconds(15), stop) ?? throw new IOException("Native Claude checkpoint observation missing");
            if (line.Length > 65536 || process.ObserveOwner() != owner) throw new InvalidDataException("Claude checkpoint owner/generation changed");
            var value = JsonDocument.Parse(line).RootElement;
            if (value.GetProperty("type").GetString() != "ccrelay_claude_snapshot" || value.GetProperty("uid").GetInt32() != 1000 ||
                value.GetProperty("session_id").GetString() != target.ThreadId || value.GetProperty("workspace").GetString() != target.Workspace ||
                value.GetProperty("source_writer").GetString() != "quiesced" || value.GetProperty("model_inference").GetBoolean() ||
                value.GetProperty("history").ValueKind != JsonValueKind.Object)
                throw new InvalidDataException("Exact quiesced saved native history required; no fresh fallback");
            digest = WriteCheckpoint(path, new { schema = "ccrelay.personal_claude_handoff.v1", session_id = target.ThreadId,
                workspace = target.Workspace, source_writer = "quiesced", uncertain_actions = Array.Empty<string>(),
                history = value.GetProperty("history").Clone(), profile = "/Users/pouya/.claude" }, create: false);
        }
        var effective = policy with { LinuxClaude = For(target, digest, model) };
        ledger.Put(CheckpointKey(target), new { binding = target, sha256 = digest, model, state = "launch-attempted", at = DateTimeOffset.UtcNow });
        // This intent is one-shot per explicit switch. Failed opens remain in
        // the protected switch journal and cannot be silently repeated.
        var channel = await LinuxClaudeChannel.Open(effective, target, stop);
        if (runtime.GuardedRecovery)
            ledger.Put(RecoveryKey(target), new { binding = target, sha256 = digest, model, state = "connected", at = DateTimeOffset.UtcNow });
        return new ClaudeNativeStream(channel, ledger, target.ThreadId);
    }
    private LinuxClaudeRuntime For(Binding target, string digest, string? model = null)
    {
        if (!LinuxClaudeRuntime.Digest(digest)) throw new InvalidDataException("Exact switch checkpoint SHA256 required");
        var checkpoints = runtime!.Checkpoints.Where(p => p.Value.Chat != target.Chat || p.Value.Topic != target.Topic).ToDictionary(p => p.Key, p => p.Value);
        checkpoints[target.ThreadId] = new(target.Chat, target.Topic, target.Workspace, digest, model);
        return runtime with { Checkpoints = checkpoints };
    }
    private string WriteCheckpoint(string path, object checkpoint, bool create)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var body = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(checkpoint));
        using (var file = new FileStream(path, create ? FileMode.CreateNew : FileMode.Truncate, FileAccess.Write, FileShare.None))
        { file.Write(body); file.Flush(true); }
        var acl = new FileSecurity(); acl.SetAccessRuleProtection(true, false); acl.SetOwner(new SecurityIdentifier("S-1-5-32-544"));
        foreach (var sid in new[] { "S-1-5-18", "S-1-5-32-544" }) acl.AddAccessRule(new(new SecurityIdentifier(sid), FileSystemRights.FullControl, AccessControlType.Allow));
        acl.AddAccessRule(new(new SecurityIdentifier(policy.OwnerSid), FileSystemRights.Read, AccessControlType.Allow));
        new FileInfo(path).SetAccessControl(acl);
        return Convert.ToHexString(SHA256.HashData(body)).ToLowerInvariant();
    }
}
