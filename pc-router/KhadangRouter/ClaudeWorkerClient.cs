using System.Text.Json;

namespace KhadangRouter;

internal sealed record ClaudeHostEndpoint(string Pipe, WindowsPipePin Server);
internal sealed record ClaudeWorkerEndpoint(string Pipe, WindowsPipePin Server, string Epoch, uint NativePid, Binding Binding);
internal sealed record ClaudeWorkerOpen(string Id, Binding Binding, Binding? Source, bool Fresh, string? Model);

// Client disposal NEVER stops the host or native worker. The protected broker
// journals complete events while this UI is offline; cursors survive restarts.
internal sealed class ClaudeWorkerClient : IClaudeNative
{
    private readonly NativeBrokerWireClient client;
    private readonly Ledger ledger;
    private readonly ClaudeWorkerEndpoint endpoint;
    private readonly CancellationTokenSource stop = new();
    private Task? reader;
    private bool disconnected;
    private readonly string cursorKey;
    private string LeaseKey => "claude/worker-lease/" + SessionId;
    internal bool ReattachedGeneration { get; }
    public uint Pid => endpoint.NativePid;
    public string SessionId => endpoint.Binding.ThreadId;
    public bool Connected => !disconnected;
    public event Action<JsonElement>? Notification;
    private ClaudeWorkerClient(NativeBrokerWireClient client, Ledger ledger, ClaudeWorkerEndpoint endpoint)
    {
        this.client = client; this.ledger = ledger; this.endpoint = endpoint;
        cursorKey = "claude/worker-cursor/" + SessionId + "/" + endpoint.Epoch;
        ReattachedGeneration = ledger.Get(LeaseKey)?.Deserialize<ClaudeWorkerEndpoint>() == endpoint;
    }
    internal static ClaudeWorkerClient Fixture(NativeBrokerWireClient client, Ledger ledger, Binding binding, string epoch, uint pid) =>
        new(client, ledger, new(epoch, new(1, 1, @"C:\Fixture\host.exe", new string('a', 64)), epoch, pid, binding));
    internal static async Task<IClaudeNative> Open(RouterPolicy policy, Ledger ledger, Binding binding,
        Binding? source, bool fresh, string? model, CancellationToken stop)
    {
        WindowsPipePeer.RequireSystem();
        WindowsPipePeer.ProtectedPath(ClaudeWorkerHost.Root + "\\host.json", ClaudeWorkerHost.Root, false);
        var hub = JsonSerializer.Deserialize<ClaudeHostEndpoint>(File.ReadAllText(ClaudeWorkerHost.Root + "\\host.json"))
            ?? throw new InvalidDataException("Protected Claude host endpoint missing");
        var (pipe, peer) = await WindowsPipePeer.Connect(hub.Pipe, hub.Server, ClaudeWorkerHost.Root, stop);
        ClaudeWorkerEndpoint endpoint;
        using (pipe) using (peer) using (var writes = new SemaphoreSlim(1, 1))
        {
            var id = Guid.NewGuid().ToString("N");
            await BrokerWireFrames.Write(pipe, new ClaudeWorkerOpen(id, binding, source, fresh, model), writes, stop);
            var reply = await BrokerWireFrames.Read(pipe, stop) ?? throw new IOException("Claude host open reply missing");
            if (reply.GetProperty("Id").GetString() != id || reply.GetProperty("Status").GetString() != "ready")
                throw new IOException("Claude host refused this exact session; no replacement or replay");
            endpoint = reply.GetProperty("Endpoint").Deserialize<ClaudeWorkerEndpoint>() ?? throw new InvalidDataException("Claude worker lease missing");
        }
        if (endpoint.Binding != binding || endpoint.Server != hub.Server || endpoint.NativePid == 0)
            throw new InvalidDataException("Claude worker lease is for a different native conversation");
        var wire = await NativeBrokerWireClient.Connect(endpoint.Pipe, endpoint.Server, endpoint.Epoch, ClaudeWorkerHost.Root, stop);
        return new ClaudeWorkerClient(wire, ledger, endpoint);
    }
    public async Task<JsonElement> Initialize(CancellationToken token)
    {
        if (reader != null) throw new InvalidOperationException("Worker client initialization is one-shot");
        var information = await Call("claude/status/read", new { }, token);
        var keys = new[] { "claude/launch-handoff/" + SessionId, LinuxClaudeTopics.RecoveryKey(endpoint.Binding), "claude/switch-checkpoint/" + SessionId };
        foreach (var key in keys)
            if (information.GetProperty("worker_metadata").TryGetProperty(key, out var value)) ledger.Put(key, value);
        ledger.Put(LeaseKey, endpoint);
        reader = Task.Run(Read);
        return information;
    }
    internal async Task RestoreRequests(CancellationToken token)
    {
        var live = await Call("claude/status/read", new { }, token);
        foreach (var request in live.GetProperty("worker_pending_requests").EnumerateArray()) Notification?.Invoke(request.Clone());
    }
    internal Task<JsonElement> Remote(CancellationToken token) => Call("claude/remote/read", new { }, token);
    public Task<JsonElement> Control(string subtype, object parameters, CancellationToken token, bool effect = true) =>
        subtype == "get_usage" && !effect ? Call("claude/usage/read", parameters, token) :
            Call("claude/control", new { subtype, parameters, effect }, token);
    private Task<JsonElement> Call(string method, object parameters, CancellationToken token) =>
        client.Call(Guid.NewGuid().ToString("N"), method, parameters, token);
    public async Task<JsonElement> SendNow(string expectedSessionId, JsonElement content, CancellationToken token)
    {
        if (expectedSessionId != SessionId) throw new InvalidDataException("Claude input belongs to another worker");
        var uuid = Guid.NewGuid().ToString("D");
        var operation = ledger.Attempt("claude/user/send-now", new { SessionId, uuid, content });
        try
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token); deadline.CancelAfter(TimeSpan.FromSeconds(35));
            var replay = await client.Call(operation, "claude/send", new { uuid, content }, deadline.Token);
            if (ClaudeDelivery.ConfirmReplay(ledger, SessionId, replay) != operation)
                throw new InvalidDataException("Exact native Claude user receipt missing");
            return replay;
        }
        catch (OperationCanceledException) when (!token.IsCancellationRequested)
        { ledger.Outcome(operation, "unknown"); throw new ClaudeDeliveryTimeout(operation, SessionId, uuid); }
        catch (IOException)
        { ledger.Outcome(operation, "unknown"); throw new ClaudeDeliveryTimeout(operation, SessionId, uuid); }
        catch { ledger.Outcome(operation, "unknown"); throw; }
    }
    public async Task Answer(string requestId, object answer, CancellationToken token)
    {
        var operation = ledger.Attempt("claude/control/answer", new { SessionId, requestId, answer });
        try { await client.Call(operation, "claude/answer", new { requestId, answer }, token); }
        finally { ledger.Outcome(operation, "unknown"); } // Native write is not permission acceptance.
    }
    public async ValueTask RetireForSwitch(CancellationToken token)
    { await Call("claude/retire", new { }, token); await DisposeAsync(); }
    private async Task Read()
    {
        long cursor = ledger.Get(cursorKey)?.GetProperty("position").GetInt64() ?? 0;
        try
        {
            while (!stop.IsCancellationRequested)
            {
                var page = await client.Events(cursor, 100, stop.Token);
                foreach (var item in page)
                {
                    var frame = item.Frame;
                    if (frame.TryGetProperty("type", out var type) && type.GetString() == "ccrelay_delivery_confirmed")
                    { /* Host-local operation IDs are not router delivery receipts. */ }
                    else
                    {
                        var confirmed = ClaudeDelivery.ConfirmReplay(ledger, SessionId, frame);
                        if (confirmed != null) Notification?.Invoke(JsonSerializer.SerializeToElement(new {
                            type = "ccrelay_delivery_confirmed", session_id = SessionId, operation = confirmed, uuid = frame.GetProperty("uuid").GetString() }));
                        Notification?.Invoke(frame);
                    }
                    cursor = item.Position; ledger.Put(cursorKey, new { position = cursor });
                }
                if (page.Count == 0) await Task.Delay(500, stop.Token);
            }
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or InvalidDataException or JsonException or InvalidOperationException) { }
        finally { disconnected = true; }
    }
    public async ValueTask DisposeAsync()
    {
        if (disconnected && stop.IsCancellationRequested) return;
        disconnected = true; stop.Cancel(); await client.DisposeAsync();
        if (reader != null) await reader;
    }
}
