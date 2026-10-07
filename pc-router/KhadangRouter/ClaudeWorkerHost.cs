using System.Diagnostics;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;

namespace KhadangRouter;

// Independent SYSTEM custody component. It never loads the Telegram token or
// polls Telegram. Actual agents still run through the attested limited owner.
internal sealed class ClaudeWorkerHost : IAsyncDisposable
{
    internal const string Root = @"C:\ProgramData\KhadangClaudeHost";
    internal const string RouterRoot = @"C:\ProgramData\KhadangRouter";
    internal const string ServiceName = "KhadangClaudeHost";
    private sealed record Worker(NativeBroker Broker, ClaudeWorkerNative Native, WindowsProtectedPipe Pipe,
        ClaudeWorkerEndpoint Endpoint, CancellationTokenSource Stop, Task Listener);
    private readonly Dictionary<string, Worker> workers = [];
    private readonly WindowsPipePin server;
    private ClaudeWorkerHost()
    {
        WindowsPipePeer.RequireSystem();
        var image = Environment.ProcessPath ?? throw new InvalidDataException("Host executable missing");
        server = WindowsPipePeer.Capture((uint)Environment.ProcessId, image, Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(image))));
    }
    internal static async Task Run(CancellationToken stop)
    {
        WindowsPipePeer.RequireSystem();
        WindowsPipePeer.ProtectedPath(Root + "\\state", Root, true);
        using var lease = new FileStream(Root + "\\state\\host.lock", FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        await using var host = new ClaudeWorkerHost();
        var run = Guid.NewGuid().ToString("N"); using var hub = new WindowsProtectedPipe(run);
        File.WriteAllText(Root + "\\host.json", JsonSerializer.Serialize(new ClaudeHostEndpoint(run, host.server)));
        while (!stop.IsCancellationRequested)
        {
            await hub.Stream.WaitForConnectionAsync(stop);
            try
            {
                using var peer = AuthenticateRouter(hub.Stream);
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stop); deadline.CancelAfter(TimeSpan.FromSeconds(60));
                var frame = await BrokerWireFrames.Read(hub.Stream, deadline.Token) ?? throw new IOException("Host request missing");
                var request = frame.Deserialize<ClaudeWorkerOpen>(BrokerWireFrames.Json) ?? throw new InvalidDataException("Exact host request required");
                if (!Guid.TryParseExact(request.Id, "N", out _)) throw new InvalidDataException("Exact request identity required");
                object response;
                try { response = new { request.Id, Status = "ready", Endpoint = await host.Open(request, stop) }; }
                catch (Exception error) when (error is IOException or InvalidDataException or InvalidOperationException or UnauthorizedAccessException)
                { response = new { request.Id, Status = "held" }; }
                using var writes = new SemaphoreSlim(1, 1);
                await BrokerWireFrames.Write(hub.Stream, response, writes, deadline.Token);
                // Windows Disconnect() can discard unread reply bytes even
                // after FlushAsync. Keep this connection until the client,
                // which closes only AFTER its complete reply, reaches EOF.
                if (await BrokerWireFrames.Read(hub.Stream, deadline.Token) != null)
                    throw new InvalidDataException("One exact open per host connection required");
            }
            catch (Exception error) when (error is IOException or InvalidDataException or OperationCanceledException or JsonException or System.ComponentModel.Win32Exception) { }
            finally { if (hub.Stream.IsConnected) hub.Stream.Disconnect(); }
        }
    }
    private static WindowsPipePeer AuthenticateRouter(System.IO.Pipes.NamedPipeServerStream pipe)
    {
        // Kernel SID/session + current protected router image, not forum role,
        // UID, a claimed process ID, or a worker-selected executable.
        var image = RouterRoot + "\\bin\\KhadangRouter.exe";
        WindowsPipePeer.ProtectedPath(image, RouterRoot, false);
        var digest = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(image)));
        return WindowsPipePeer.AuthenticateImage(pipe, false, image, digest, RouterRoot);
    }
    private async Task<ClaudeWorkerEndpoint> Open(ClaudeWorkerOpen request, CancellationToken stop)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var target = request.Binding;
        if (!LinuxClaudeRuntime.Session(target.ThreadId) || target.Backend != "claude" || target.Runtime != "linux")
            throw new InvalidDataException("Exact native Claude binding required");
        var policy = RouterPolicy.Load(RouterRoot + "\\config.json");
        if (!policy.PersistentClaudeWorkers) throw new InvalidDataException("Persistent host is not enabled by protected policy");
        policy.ValidateBindings([target]);
        using var source = Ledger.ReadOnly(policy.StateDirectory + "\\router.db");
        var bindings = source.Bindings();
        var actual = bindings.SingleOrDefault(b => b.Address == target.Address);
        if (request.Source == null)
        {
            if (actual != target || request.Fresh || request.Model != null) throw new InvalidDataException("Normal attachment cannot change a session/model");
        }
        else
        {
            var intent = source.Get($"model-switch/{target.Chat}/{target.Topic}");
            if (actual != request.Source || actual.Address != target.Address || actual.Workspace != target.Workspace ||
                source.Get(ModelCommand.Slot(target.Address, "claude"))?.Deserialize<Binding>() != target ||
                intent is not { } ownerIntent || ownerIntent.GetProperty("phase").GetString() != "opening-destination" ||
                ownerIntent.GetProperty("source").Deserialize<Binding>() != request.Source || ownerIntent.GetProperty("target").Deserialize<Binding>() != target ||
                !string.Equals(ownerIntent.GetProperty("requestedModel").GetString(), request.Model, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Explicit protected owner switch enrollment required");
        }
        if (workers.TryGetValue(target.ThreadId, out var current))
        {
            if (current.Endpoint.Binding != target) throw new InvalidDataException("Native worker scope cannot move");
            if (!current.Native.Retired)
            {
                if (!current.Native.Connected || request.Source != null && !current.Native.Idle)
                    throw new InvalidOperationException("Existing worker cannot be replaced or restarted implicitly");
                return current.Endpoint;
            }
            current.Stop.Cancel();
            try { await current.Listener; } catch (OperationCanceledException) { }
            current.Pipe.Dispose();
            await current.Broker.DisposeAsync(); current.Stop.Dispose(); workers.Remove(target.ThreadId);
        }
        if (source.Unknown != 0 || request.Source == null && source.Query("SELECT id FROM updates WHERE status='dispatching'").Count != 0)
            throw new InvalidOperationException("Uncertain router input holds native launch");
        var directory = Root + "\\state\\" + target.ThreadId;
        if (!Directory.Exists(directory))
        {
            Directory.CreateDirectory(directory);
            var acl = new DirectorySecurity(); acl.SetAccessRuleProtection(true, false); acl.SetOwner(new SecurityIdentifier("S-1-5-18"));
            foreach (var sid in new[] { "S-1-5-18", "S-1-5-32-544" })
                acl.AddAccessRule(new(new SecurityIdentifier(sid), FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
            new DirectoryInfo(directory).SetAccessControl(acl);
        }
        ClaudeWorkerNative? adapter = null;
        var broker = await NativeBroker.OwnClaude(directory, Root, async ledger => {
            if (ledger.Unknown != 0) throw new InvalidOperationException("Uncertain worker history cannot be resumed automatically");
            foreach (var table in new[] { "broker_calls", "broker_replies" })
                if (ledger.Query("SELECT name FROM sqlite_master WHERE type='table' AND name=?", table).Count != 0 &&
                    ledger.Query("SELECT 1 FROM " + table + " WHERE status IN ('attempting','unknown','submitted') LIMIT 1").Count != 0)
                    throw new InvalidOperationException("Uncertain broker action holds native recovery");
            foreach (var b in bindings) ledger.Exec("INSERT INTO bindings VALUES (?,?,?) ON CONFLICT(chat,topic) DO UPDATE SET payload=excluded.payload", b.Chat, b.Topic, JsonSerializer.Serialize(b));
            foreach (var b in bindings.Where(b => b.Backend == "claude"))
                if (source.Get(ModelCommand.Slot(b.Address, "claude")) is { } savedSlot) ledger.Put(ModelCommand.Slot(b.Address, "claude"), savedSlot);
            var keys = new[] { "bubble/" + target.ThreadId, "claude/remote/" + target.ThreadId, "claude/launch-handoff/" + target.ThreadId,
                LinuxClaudeTopics.RecoveryKey(target), "claude/switch-checkpoint/" + target.ThreadId, ModelCommand.Slot(target.Address, "claude") };
            foreach (var key in keys)
                if (source.Get(key) is { } value && (key.StartsWith("bubble/", StringComparison.Ordinal) || ledger.Get(key) == null)) ledger.Put(key, value);
            var launcher = new LinuxClaudeTopics(policy with { PersistentClaudeWorkers = false }, ledger, bindings);
            var native = request.Source == null ? await launcher.Open(target, stop) :
                await launcher.OpenForSwitch(request.Source, target, request.Fresh, request.Model, stop);
            adapter = new ClaudeWorkerNative(native, target, ledger);
            return adapter;
        });
        try
        {
            await broker.Ready.WaitAsync(stop);
            var run = Guid.NewGuid().ToString("N"); var pipe = new WindowsProtectedPipe(run);
            var endpoint = new ClaudeWorkerEndpoint(run, server, broker.Epoch, broker.Pid, target);
            var lifetime = CancellationTokenSource.CreateLinkedTokenSource(stop);
            var listener = ServeWorker(broker, pipe, lifetime.Token);
            workers.Add(target.ThreadId, new(broker, adapter!, pipe, endpoint, lifetime, listener));
            File.WriteAllText(directory + "\\endpoint.json", JsonSerializer.Serialize(endpoint));
            return endpoint;
        }
        catch { await broker.DisposeAsync(); throw; }
    }
    private static async Task ServeWorker(NativeBroker broker, WindowsProtectedPipe pipe, CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            try
            {
                await pipe.Stream.WaitForConnectionAsync(stop);
                using var peer = AuthenticateRouter(pipe.Stream);
                using var attached = broker.Attach(peer);
                await NativeBrokerWire.ServeAttached(attached, pipe.Stream, request => {
                    if (request.Kind is "status" or "events") return;
                    if (request.Kind != "call" || request.Method is not ("claude/status/read" or "claude/remote/read" or "claude/usage/read" or
                        "claude/send" or "claude/answer" or "claude/control" or "claude/retire"))
                        throw new InvalidDataException("Claude worker endpoint has no generic native/company API");
                }, stop);
            }
            catch (Exception error) when (error is IOException or InvalidDataException or JsonException or System.ComponentModel.Win32Exception or ObjectDisposedException) { }
            finally { if (pipe.Stream.IsConnected) pipe.Stream.Disconnect(); }
        }
    }
    public async ValueTask DisposeAsync()
    {
        foreach (var worker in workers.Values) { worker.Stop.Cancel(); worker.Pipe.Dispose(); }
        foreach (var worker in workers.Values)
        {
            try { await worker.Listener; } catch (Exception error) when (error is OperationCanceledException or ObjectDisposedException or IOException) { }
            await worker.Broker.DisposeAsync(); worker.Stop.Dispose();
        }
    }
}
