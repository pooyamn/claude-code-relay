using System.ComponentModel;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

// Existing personal-owner launcher only; no company identities or broker.
// Each checkpoint authorizes one exact topic/workspace/native conversation.
public sealed record ClaudeCheckpoint(long Chat, int Topic, string Workspace, string Sha256, string? Model = null);
public sealed record LinuxClaudeRuntime(string PackageRoot, string WslSha256, Dictionary<string, string> FileSha256,
    Dictionary<string, ClaudeCheckpoint> Checkpoints, bool GuardedRecovery = false)
{
    public const string BinarySha256 = "0298068b686e7fdbaf9402a7a587bb7f49c0b0e084de09f69145a0719207640c";
    public const string HeldSession = "b728b1bc-3d36-4178-aa01-fd9e9b056d9c";
    internal static readonly string[] PackageFiles = [ "pc_claude_stdio.py", .. LinuxCodexRuntime.PackageFiles ];
    internal static bool Digest(string? value) => value is { Length: 64 } && value.All(Uri.IsHexDigit);
    internal static bool Session(string? value) => value != HeldSession && Guid.TryParseExact(value, "D", out var id) && id.ToString("D") == value;
    public void Validate()
    {
        if (PackageRoot == null || !Regex.IsMatch(PackageRoot, @"\AC:\\ProgramData\\OracovaNativeRemote\\claude-connector-[a-f0-9]{32}\z") ||
            !Digest(WslSha256) || FileSha256 == null || FileSha256.Count != PackageFiles.Length ||
            !PackageFiles.All(name => FileSha256.TryGetValue(name, out var digest) && Digest(digest)) ||
            Checkpoints == null || Checkpoints.Count is < 1 or > 256)
            throw new InvalidDataException("Exact protected Claude connector package, digests and checkpoints required");
        var addresses = new HashSet<TopicAddress>();
        foreach (var (session, checkpoint) in Checkpoints)
        {
            if (!Session(session) || checkpoint == null || checkpoint.Workspace == null || checkpoint.Chat >= 0 || checkpoint.Topic < 0 ||
                !Digest(checkpoint.Sha256) || checkpoint.Sha256 != checkpoint.Sha256.ToLowerInvariant() ||
                !addresses.Add(new(checkpoint.Chat, checkpoint.Topic)) || checkpoint.Model != null && !Regex.IsMatch(checkpoint.Model, @"\A[A-Za-z0-9][A-Za-z0-9._\[\]-]*\z"))
                throw new InvalidDataException("Exact unique saved Claude checkpoints required");
            LinuxCodexRuntime.ValidateWorkspaces([checkpoint.Workspace]);
        }
    }
    internal ClaudeCheckpoint For(Binding binding)
    {
        Validate();
        if (binding.Backend != "claude" || binding.Runtime != "linux" || !Session(binding.ThreadId) ||
            !Checkpoints.TryGetValue(binding.ThreadId, out var checkpoint) || checkpoint.Chat != binding.Chat ||
            checkpoint.Topic != binding.Topic || checkpoint.Workspace != binding.Workspace)
            throw new InvalidDataException("Claude checkpoint does not authorize the exact selected topic/session/workspace");
        return checkpoint;
    }
    internal string CheckpointPath(Binding binding)
    { For(binding); return PackageRoot + "\\handoff-" + binding.ThreadId + ".json"; }
    internal string Arguments(Binding binding, bool ownerFullAccess)
    {
        var checkpoint = For(binding);
        var root = "/mnt/c/" + PackageRoot[3..].Replace('\\', '/');
        return "-d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B " + LinuxCodexRuntime.Quote(root + "/pc_claude_stdio.py") +
            " --workspace " + LinuxCodexRuntime.Quote(binding.Workspace) + " --session " + LinuxCodexRuntime.Quote(binding.ThreadId) +
            " --checkpoint " + LinuxCodexRuntime.Quote(root + "/handoff-" + binding.ThreadId + ".json") +
            " --checkpoint-sha256 " + checkpoint.Sha256 + (ownerFullAccess ? " --owner-full-access" : "") +
            (checkpoint.Model == null ? "" : " --model " + LinuxCodexRuntime.Quote(checkpoint.Model));
    }
    internal IDisposable OpenPinnedPackage(Binding binding)
    {
        var checkpoint = For(binding);
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var lease = new PackageLease();
        try
        {
            foreach (var (name, digest) in PackageFiles.Select(name => (name, FileSha256[name]))
                .Append(("handoff-" + binding.ThreadId + ".json", checkpoint.Sha256)))
            {
                var path = PackageRoot + "\\" + name.Replace('/', '\\');
                WindowsPipePeer.ProtectedPath(path, LinuxCodexRuntime.ProtectedRoot, directory: false);
                var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                lease.Files.Add(source);
                if (name.StartsWith("handoff-", StringComparison.Ordinal) && source.Length > 65536 ||
                    !Convert.ToHexString(SHA256.HashData(source)).Equals(digest, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Pinned Claude connector or reviewed handoff bytes changed");
            }
            return lease; // Prevent replacement/write through Windows until child launch.
        }
        catch { lease.Dispose(); throw; }
    }
    private sealed class PackageLease : IDisposable
    {
        public List<FileStream> Files { get; } = [];
        public void Dispose() { foreach (var file in Files) file.Dispose(); Files.Clear(); }
    }
}

public sealed record LinuxClaudeObservation(OwnerProcessObservation WindowsOwner, uint NativePid, string NativeGeneration,
    string SessionId, string Workspace, string CheckpointSha256);

public sealed class LinuxClaudeChannel : INativeChannel
{
    private readonly INativeChannel channel;
    private readonly Func<OwnerProcessObservation> observeOwner;
    private readonly Func<bool> ownedExited;
    public LinuxClaudeObservation Observation { get; }
    public uint Pid => Observation.NativePid;
    private LinuxClaudeChannel(INativeChannel channel, Func<OwnerProcessObservation> observeOwner, Func<bool> ownedExited,
        LinuxClaudeObservation observation)
    { this.channel = channel; this.observeOwner = observeOwner; this.ownedExited = ownedExited; Observation = observation; }

    public static async Task<LinuxClaudeChannel> Open(RouterPolicy policy, Binding binding, CancellationToken stop)
    {
        policy.Validate(); policy.ValidateBindings([binding]);
        var runtime = policy.LinuxClaude ?? throw new InvalidDataException("Protected Linux Claude runtime is not configured");
        var checkpoint = runtime.For(binding);
        if (policy.CredentialFile != @"C:\ProgramData\KhadangRouter\khadang-token.dpapi")
            throw new InvalidDataException("Claude credential denial requires the exact protected PC credential");
        var process = WindowsOwnerProcess.StartLinuxClaude(policy, policy.WorkspaceRoot + "\\lg-magic", binding);
        return await Accept(new StdioNativeChannel(process), process.ObserveOwner, () => process.HasExited,
            policy.OwnerSid, binding, checkpoint.Sha256, stop);
    }
    // Fixtures below validate observations/ownership, not Windows OS attestation.
    internal static async Task<LinuxClaudeChannel> Accept(INativeChannel channel, Func<OwnerProcessObservation> observeOwner,
        Func<bool> ownedExited, string ownerSid, Binding binding, string checkpoint, CancellationToken stop)
    {
        try
        {
            var owner = observeOwner(); ValidateOwner(owner, ownerSid);
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stop); deadline.CancelAfter(TimeSpan.FromSeconds(15));
            var ready = await channel.Read(deadline.Token) ?? throw new IOException("Claude connector ended before attestation");
            var observation = ParseReady(ready, owner, binding, checkpoint);
            if (observeOwner() != owner) throw new InvalidDataException("Windows Claude connector generation changed during attestation");
            return new(channel, observeOwner, ownedExited, observation);
        }
        catch { await channel.DisposeAsync(); throw; }
    }
    internal static void ValidateOwner(OwnerProcessObservation owner, string sid)
    {
        if (owner.Pid == 0 || owner.Sid != sid || owner.Sid == "S-1-5-18" || owner.Session <= 0 || owner.Elevated || owner.CreationTime <= 0)
            throw new InvalidDataException("Actual limited Windows Claude owner token/generation required");
    }
    internal static LinuxClaudeObservation ParseReady(string frame, OwnerProcessObservation owner, Binding binding, string checkpoint)
    {
        if (!LinuxClaudeRuntime.Session(binding.ThreadId) || binding.Backend != "claude" || binding.Runtime != "linux" ||
            !LinuxClaudeRuntime.Digest(checkpoint) || Encoding.UTF8.GetByteCount(frame) > 65536)
            throw new InvalidDataException("Exact bounded Claude launch observation required");
        LinuxCodexRuntime.ValidateWorkspaces([binding.Workspace]);
        try
        {
            using var doc = JsonDocument.Parse(frame); var value = doc.RootElement;
            var names = new[] { "type", "session_id", "workspace", "uid", "native_uid", "native_pid", "native_generation",
                "binary_sha256", "credential_denied", "checkpoint_sha256", "inherited_lease" };
            if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Claude launch observation must be an object");
            var observed = value.EnumerateObject().Select(field => field.Name).ToArray();
            var generation = value.GetProperty("native_generation").GetString();
            if (observed.Length != names.Length || !observed.Order(StringComparer.Ordinal).SequenceEqual(names.Order(StringComparer.Ordinal)) ||
                value.GetProperty("type").GetString() != "ccrelay_claude_ready" || value.GetProperty("session_id").GetString() != binding.ThreadId ||
                value.GetProperty("workspace").GetString() != binding.Workspace || value.GetProperty("uid").GetInt32() != 1000 ||
                value.GetProperty("native_uid").GetInt32() != 1000 || !value.GetProperty("native_pid").TryGetUInt32(out var pid) || pid == 0 ||
                generation is not { Length: > 0 and <= 32 } || !generation.All(char.IsAsciiDigit) || generation.All(c => c == '0') ||
                value.GetProperty("binary_sha256").GetString() != LinuxClaudeRuntime.BinarySha256 ||
                value.GetProperty("credential_denied").ValueKind != JsonValueKind.True || value.GetProperty("inherited_lease").ValueKind != JsonValueKind.True ||
                value.GetProperty("checkpoint_sha256").GetString() != checkpoint)
                throw new InvalidDataException("Claude native owner/image/lease/session/checkpoint observation mismatch");
            return new(owner, pid, generation, binding.ThreadId, binding.Workspace, checkpoint);
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or KeyNotFoundException or FormatException or OverflowException)
        { throw new InvalidDataException("Malformed Claude connector attestation", error); }
    }
    private void VerifyOwner(bool allowTerminal = false)
    {
        try
        {
            if (observeOwner() != Observation.WindowsOwner) throw new InvalidDataException("Owned Windows Claude token/generation changed");
        }
        catch (Win32Exception)
        {
            // This is ONLY the owned process handle and its original private
            // stdout pipe. Confirmed exit permits final output, never input.
            if (!allowTerminal || !ownedExited()) throw new IOException("Owned Windows Claude connector ended; no replay");
        }
    }
    public async Task<string?> Read(CancellationToken stop)
    {
        VerifyOwner(allowTerminal: true); var frame = await channel.Read(stop);
        if (frame == null) return null;
        VerifyOwner(allowTerminal: true);
        using var document = JsonDocument.Parse(frame);
        if (document.RootElement.TryGetProperty("type", out var kind) && kind.GetString() == "ccrelay_claude_ready")
            throw new InvalidDataException("Claude readiness must not repeat or become a native event");
        return frame;
    }
    public async Task Write(string message, CancellationToken stop)
    { VerifyOwner(); await channel.Write(message, stop); VerifyOwner(); }
    public ValueTask DisposeAsync() => channel.DisposeAsync();
}

public sealed partial class LinuxClaudeTopics : IClaudeTopics
{
    private readonly Ledger ledger;
    private readonly LinuxClaudeRuntime? runtime;
    private readonly Dictionary<TopicAddress, Binding> selected;
    private readonly HashSet<string> attempted = new(StringComparer.Ordinal);
    private readonly Func<Binding, CancellationToken, Task<INativeChannel>> open;
    private readonly Func<Binding, string, string?, CancellationToken, Task<string>> renew;
    private readonly Func<Binding, string, string?, CancellationToken, Task<INativeChannel>> openRenewed;
    public LinuxClaudeTopics(RouterPolicy policy, Ledger ledger, IReadOnlyList<Binding> bindings)
        : this(policy, ledger, bindings, async (binding, stop) => await LinuxClaudeChannel.Open(policy, binding, stop)) { }
    internal LinuxClaudeTopics(RouterPolicy policy, Ledger ledger, IReadOnlyList<Binding> bindings,
        Func<Binding, CancellationToken, Task<INativeChannel>> open,
        Func<Binding, string, string?, CancellationToken, Task<string>>? renew = null,
        Func<Binding, string, string?, CancellationToken, Task<INativeChannel>>? openRenewed = null)
    {
        ValidateRegistry(policy, bindings, ledger); this.ledger = ledger; this.open = open; runtime = policy.LinuxClaude; this.policy = policy;
        selected = bindings.ToDictionary(binding => binding.Address);
        this.renew = renew ?? RenewCheckpoint;
        this.openRenewed = openRenewed ?? (async (binding, digest, model, stop) =>
            await LinuxClaudeChannel.Open(policy with { LinuxClaude = For(binding, digest, model) }, binding, stop));
    }
    internal static void ValidateRegistry(RouterPolicy policy, IReadOnlyList<Binding> bindings, Ledger? ledger = null)
    {
        policy.Validate(); policy.ValidateBindings(bindings);
        var claude = bindings.Where(binding => binding.Backend == "claude").ToArray();
        if (claude.Length == 0) return;
        var runtime = policy.LinuxClaude ?? throw new InvalidDataException("Claude bindings require the protected exact-handoff launcher");
        foreach (var checkpoint in runtime.Checkpoints.Values)
            if (!bindings.Any(b => b.Chat == checkpoint.Chat && b.Topic == checkpoint.Topic && b.Workspace == checkpoint.Workspace))
                throw new InvalidDataException("Claude checkpoint authorizes an unregistered topic/workspace");
        foreach (var binding in claude)
            if (runtime.Checkpoints.ContainsKey(binding.ThreadId)) runtime.For(binding);
            else if (ledger?.Get(ModelCommand.Slot(binding.Address, "claude")) is not { } saved || JsonSerializer.Deserialize<Binding>(saved.GetRawText()) != binding)
                throw new InvalidDataException("Claude binding has neither an exact reviewed checkpoint nor a protected owner-switch enrollment");
    }
    internal static void RequireAcceptance(JsonElement proof)
    {
        foreach (var name in new[] { "nativeLinuxClaudeLaunchVerified", "nativeLinuxClaudeToolOwnerVerified", "nativeLinuxClaudeContinuityVerified" })
            if (!proof.TryGetProperty(name, out var evidence) || evidence.ValueKind != JsonValueKind.True)
                throw new InvalidOperationException("Matching Claude launch/tool-owner/continuity acceptance required before polling");
    }
    public async Task<IClaudeNative> Open(Binding binding, CancellationToken stop)
    {
        if (!selected.TryGetValue(binding.Address, out var original) || binding != original)
            throw new InvalidDataException("Claude launcher cannot select a substitute binding");
        if (runtime!.GuardedRecovery && (ledger.Get(CheckpointKey(binding)) != null || ledger.Get(RecoveryKey(binding)) != null ||
            ledger.Get("claude/launch-handoff/" + binding.ThreadId) is { } consumed &&
            consumed.GetProperty("checkpointSha256").GetString() == runtime.For(binding).Sha256))
            return await Recover(binding, stop);
        if (!runtime!.Checkpoints.ContainsKey(binding.ThreadId) || ledger.Get(CheckpointKey(binding)) != null)
            return await OpenForSwitch(binding, binding, false, null, stop);
        lock (attempted)
        {
            if (!attempted.Add(binding.ThreadId)) throw new InvalidOperationException("Claude launch already attempted; reconcile before any new generation");
            var digest = runtime!.For(binding).Sha256;
            var key = "claude/launch-handoff/" + binding.ThreadId;
            if (ledger.Get(key) is { } prior && prior.GetProperty("checkpointSha256").GetString() == digest)
                throw new InvalidOperationException("Claude handoff already consumed; reconcile and approve the next checkpoint before another generation");
            // Commit BEFORE launch. A crash/failed observation cannot consume
            // this same handoff again in a new router process. A new reviewed
            // checkpoint or explicit protected-ledger reconciliation is needed.
            ledger.Put(key, new { checkpointSha256 = digest, binding.Chat, binding.Topic, binding.Workspace, binding.ThreadId,
                state = "launch-attempted", at = DateTimeOffset.UtcNow });
        }
        var channel = await open(binding, stop);
        try { return new ClaudeNativeStream(channel, ledger, binding.ThreadId); }
        catch { await channel.DisposeAsync(); throw; }
    }
}
