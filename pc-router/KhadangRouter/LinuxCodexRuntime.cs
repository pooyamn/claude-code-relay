using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.ComponentModel;

namespace KhadangRouter;

// Personal-PC native connector only. This is NOT the deferred role/broker
// service and never grants company identity, starts a daemon or reconnects it.
public sealed record LinuxCodexRuntime(string PackageRoot, string WslSha256, Dictionary<string, string> FileSha256)
{
    public const string ProtectedRoot = @"C:\ProgramData\OracovaNativeRemote";
    public const string WslExecutable = @"C:\Windows\System32\wsl.exe";
    public const string WorkspaceRoot = "/Users/pouya/.openclaw/workspace";
    public const string AndroidWorkspace = "/Users/pouya/android router";
    internal static bool AdmittedWorkspace(string path) =>
        path == AndroidWorkspace || path.StartsWith(WorkspaceRoot + "/", StringComparison.Ordinal);
    public const string Socket = "/Users/pouya/.codex/app-server-control/app-server-control.sock";
    public const string BinarySha256 = "12eb3e81114588aca3b7998f4f19e8997b056aca08e57a7ca7c8a3ec8c652aad";
    internal static readonly string[] PackageFiles = [ "pc_native_stdio.py", "relay_core/__init__.py", "relay_core/contracts.py",
        "relay_core/identity.py", "relay_core/native_rpc.py", "relay_core/native_ws.py" ];
    public void Validate()
    {
        if (PackageRoot == null || !Regex.IsMatch(PackageRoot, @"\AC:\\ProgramData\\OracovaNativeRemote\\codex-connector-[a-f0-9]{32}\z") ||
            !Digest(WslSha256) || FileSha256 == null || FileSha256.Count != PackageFiles.Length ||
            !PackageFiles.All(name => FileSha256.TryGetValue(name, out var digest) && Digest(digest)))
            throw new InvalidDataException("Exact protected Linux connector package and image digests required");
    }
    private static bool Digest(string? value) => value is { Length: 64 } && value.All(Uri.IsHexDigit);
    internal IDisposable OpenPinnedPackage()
    {
        Validate();
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var opened = new PackageLease();
        try
        {
            foreach (var name in PackageFiles)
            {
                var path = PackageRoot + "\\" + name.Replace('/', '\\');
                // Reuse the existing pure OS-ACL check; no pipe/broker is started.
                WindowsPipePeer.ProtectedPath(path, ProtectedRoot, directory: false);
                var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                opened.Files.Add(source);
                if (!Convert.ToHexString(SHA256.HashData(source)).Equals(FileSha256[name], StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Pinned Linux connector bytes changed");
            }
            return opened; // Prevent write/replace until the limited child starts.
        }
        catch { opened.Dispose(); throw; }
    }
    internal string Arguments(IReadOnlyList<string> workspaces)
    {
        Validate(); ValidateWorkspaces(workspaces);
        var script = "/mnt/c/" + PackageRoot[3..].Replace('\\', '/') + "/pc_native_stdio.py";
        return "-d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B " + Quote(script) + " --attest" +
            string.Concat(workspaces.Select(path => " --workspace " + Quote(path)));
    }
    internal static void ValidateWorkspaces(IReadOnlyList<string> workspaces)
    {
        if (workspaces.Count is < 1 or > 256 || workspaces.Distinct(StringComparer.Ordinal).Count() != workspaces.Count ||
            workspaces.Any(path => RouterPolicy.LinuxPath(path) != path || !AdmittedWorkspace(path)))
            throw new InvalidDataException("Exact unique preserved Linux Codex workspaces required");
    }
    internal static string Quote(string value)
    {
        if (value.Any(char.IsControl)) throw new InvalidDataException("Control characters cannot be launch arguments");
        var result = new StringBuilder("\""); int slashes = 0;
        foreach (var character in value)
        {
            if (character == '\\') { slashes++; continue; }
            result.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
            result.Append(character); slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }
    private sealed class PackageLease : IDisposable
    {
        public List<FileStream> Files { get; } = [];
        public void Dispose() { foreach (var file in Files) file.Dispose(); Files.Clear(); }
    }
}

public sealed record LinuxCodexObservation(OwnerProcessObservation WindowsOwner, int Uid, uint NativePid,
    string NativeGeneration, string Socket, string SocketEndpoint, string BinarySha256, string[] Workspaces);
public sealed record LinuxCodexConnection(NativeRpc Rpc, LinuxCodexObservation Observation);

public sealed class LinuxCodexChannel : INativeChannel
{
    private readonly INativeChannel channel;
    private readonly Func<OwnerProcessObservation> observeOwner;
    public LinuxCodexObservation Observation { get; }
    public uint Pid => Observation.NativePid;
    private LinuxCodexChannel(INativeChannel channel, Func<OwnerProcessObservation> observeOwner, LinuxCodexObservation observation)
    { this.channel = channel; this.observeOwner = observeOwner; Observation = observation; }

    public static async Task<LinuxCodexChannel> Open(RouterPolicy policy, IReadOnlyList<Binding> bindings, string windowsWorkspace, CancellationToken stop)
    {
        policy.Validate(); policy.ValidateBindings(bindings);
        var runtime = policy.LinuxCodex ?? throw new InvalidDataException("Protected Linux Codex runtime is not configured");
        if (policy.CredentialFile != @"C:\ProgramData\KhadangRouter\khadang-token.dpapi")
            throw new InvalidDataException("Linux credential denial probe requires the exact protected PC credential");
        var workspaces = bindings.Where(b => b.Runtime == "linux")
            .Select(b => b.Workspace).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        LinuxCodexRuntime.ValidateWorkspaces(workspaces);
        var process = WindowsOwnerProcess.StartLinuxCodex(policy, windowsWorkspace, workspaces);
        return await Accept(new StdioNativeChannel(process), process.ObserveOwner, policy.OwnerSid, workspaces, stop);
    }
    public static async Task<LinuxCodexConnection> ConnectVerified(RouterPolicy policy, IReadOnlyList<Binding> bindings, Ledger ledger, CancellationToken stop)
    {
        var channel = await Open(policy, bindings, policy.WorkspaceRoot + "\\lg-magic", stop);
        var rpc = new NativeRpc(channel, ledger);
        try
        {
            await rpc.Initialize(stop);
            await VerifyNative(rpc, channel.Observation.Workspaces[0], stop);
            return new(rpc, channel.Observation);
        }
        catch { await rpc.DisposeAsync(); throw; }
    }
    internal static async Task VerifyNative(INative rpc, string workspace, CancellationToken stop)
    {
        LinuxCodexRuntime.ValidateWorkspaces([workspace]);
        var account = await rpc.Call("account/read", new { refreshToken = false }, stop, effect: false);
        if (!account.TryGetProperty("account", out var nativeAccount) || nativeAccount.ValueKind != JsonValueKind.Object ||
            !nativeAccount.TryGetProperty("type", out var type) || type.GetString() != "chatgpt")
            throw new InvalidDataException("Linux native Codex requires the owner's existing ChatGPT account, not API credentials");
        // Fixed read-only native tool: prove the real executor UID before
        // any resume, model input or Telegram poll. Not a model/auth test.
        var identity = await rpc.Call("command/exec", new { command = new[] { "/usr/bin/id", "-u" },
            cwd = workspace, sandboxPolicy = new { type = "dangerFullAccess" }, timeoutMs = 10000 }, stop, effect: false);
        if (identity.GetProperty("exitCode").GetInt32() != 0 || identity.GetProperty("stdout").GetString()?.Trim() != "1000")
            throw new InvalidDataException("Linux native tool executor is not the ordinary owner");
    }

    // Internal test seam: fakes exercise validation/cleanup, never OS attestation.
    internal static async Task<LinuxCodexChannel> Accept(INativeChannel channel, Func<OwnerProcessObservation> observeOwner,
        string ownerSid, string[] workspaces, CancellationToken stop)
    {
        try
        {
            LinuxCodexRuntime.ValidateWorkspaces(workspaces);
            var owner = observeOwner(); ValidateOwner(owner, ownerSid);
            using var readyStop = CancellationTokenSource.CreateLinkedTokenSource(stop);
            readyStop.CancelAfter(TimeSpan.FromSeconds(15));
            var frame = await channel.Read(readyStop.Token) ?? throw new IOException("Linux connector ended before attestation");
            var observation = ParseReady(frame, owner, workspaces);
            if (observeOwner() != owner) throw new InvalidDataException("Windows connector generation changed during attestation");
            return new(channel, observeOwner, observation);
        }
        catch { await channel.DisposeAsync(); throw; }
    }
    private static void ValidateOwner(OwnerProcessObservation owner, string sid)
    {
        if (owner.Pid == 0 || owner.Sid != sid || owner.Sid == "S-1-5-18" || owner.Session <= 0 || owner.Elevated || owner.CreationTime <= 0)
            throw new InvalidDataException("Live limited Windows owner token/generation required");
    }
    internal static LinuxCodexObservation ParseReady(string frame, OwnerProcessObservation owner, string[] workspaces)
    {
        if (Encoding.UTF8.GetByteCount(frame) > 65536) throw new InvalidDataException("Linux connector attestation exceeds bound");
        try
        {
            using var doc = JsonDocument.Parse(frame); var ready = doc.RootElement;
            Exact(ready, ["method", "params"]);
            if (ready.GetProperty("method").GetString() != "ccrelay/transport/ready") throw new InvalidDataException("Missing Linux connector attestation");
            var metadata = ready.GetProperty("params");
            Exact(metadata, ["uid", "peerUid", "peerPid", "peerGeneration", "socket", "socketEndpoint", "binarySha256", "credentialDenied", "workspaces"]);
            var generation = metadata.GetProperty("peerGeneration").GetString();
            var endpoint = metadata.GetProperty("socketEndpoint").GetString();
            var shortSocket = "/tmp/codex-daemon-1000/" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(LinuxCodexRuntime.Socket))).ToLowerInvariant();
            var paths = metadata.GetProperty("workspaces").EnumerateArray().Select(item => item.GetString()!).ToArray();
            if (metadata.GetProperty("uid").GetInt32() != 1000 || metadata.GetProperty("peerUid").GetInt32() != 1000 ||
                !metadata.GetProperty("peerPid").TryGetUInt32(out var pid) || pid == 0 || generation is not { Length: > 0 and <= 32 } ||
                !generation.All(char.IsAsciiDigit) || generation.All(c => c == '0') ||
                metadata.GetProperty("socket").GetString() != LinuxCodexRuntime.Socket || endpoint != LinuxCodexRuntime.Socket && endpoint != shortSocket ||
                metadata.GetProperty("binarySha256").GetString() != LinuxCodexRuntime.BinarySha256 ||
                metadata.GetProperty("credentialDenied").ValueKind != JsonValueKind.True || !paths.SequenceEqual(workspaces, StringComparer.Ordinal))
                throw new InvalidDataException("Linux connector peer/path/credential observation mismatch");
            return new(owner, 1000, pid, generation, LinuxCodexRuntime.Socket, endpoint!, LinuxCodexRuntime.BinarySha256, paths);
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or KeyNotFoundException or FormatException or OverflowException)
        { throw new InvalidDataException("Malformed Linux connector attestation", error); }
    }
    private static void Exact(JsonElement value, string[] names)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Exact connector object required");
        var observed = value.EnumerateObject().Select(item => item.Name).ToArray();
        if (observed.Length != names.Length || !observed.Order(StringComparer.Ordinal).SequenceEqual(names.Order(StringComparer.Ordinal)))
            throw new InvalidDataException("Unexpected or duplicate connector fields");
    }
    private void VerifyOwner()
    {
        try
        {
            if (observeOwner() != Observation.WindowsOwner) throw new InvalidDataException("Owned Windows connector token/generation changed");
        }
        catch (Win32Exception) { throw new IOException("Owned Windows connector ended; no reconnect or replay"); }
    }
    public async Task<string?> Read(CancellationToken stop)
    {
        VerifyOwner(); var frame = await channel.Read(stop);
        if (frame == null) return null; // Parent exit at EOF is terminal, not a new connection.
        VerifyOwner();
        using var document = JsonDocument.Parse(frame);
        if (document.RootElement.TryGetProperty("method", out var method) && method.GetString() == "ccrelay/transport/ready")
            throw new InvalidDataException("Linux connector attestation must not repeat or become a native event");
        return frame;
    }
    public async Task Write(string message, CancellationToken stop)
    { VerifyOwner(); await channel.Write(message, stop); VerifyOwner(); }
    public ValueTask DisposeAsync() => channel.DisposeAsync();
}
