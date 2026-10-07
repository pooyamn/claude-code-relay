using System.Text.Json;
using System.Text.Json.Nodes;

namespace KhadangRouter;

// Custody stays in KhadangClaudeHost. A router is only an attached observer;
// cached initialization/Remote Control reads never re-register a cloud session.
internal sealed class ClaudeWorkerNative(IClaudeNative native, Binding binding, Ledger ledger) : INative, IAsyncDisposable
{
    private readonly object gate = new();
    private JsonElement information, remote;
    private string state = "idle";
    public bool Retired { get; private set; }
    public bool Connected => Retired || native.Connected;
    internal bool Idle { get { lock (gate) return state == "idle"; } }
    public uint Pid => native.Pid;
    public event Action<JsonElement>? Notification;
    public async Task Initialize()
    {
        native.Notification += Observe;
        information = await native.Initialize(CancellationToken.None);
        state = information.GetProperty("session_state").GetString()!;
        var receipt = await ClaudeRemoteControl.Enable(native, binding, ledger, CancellationToken.None);
        remote = JsonSerializer.SerializeToElement(new { bridge_session_id = receipt.BridgeSessionId, session_url = receipt.SessionUrl });
    }
    private void Observe(JsonElement frame)
    {
        lock (gate)
            if (frame.TryGetProperty("type", out var type) && type.GetString() == "system" &&
                frame.TryGetProperty("subtype", out var subtype) && subtype.GetString() == "session_state_changed")
                state = frame.GetProperty("state").GetString()!;
        Notification?.Invoke(frame);
    }
    public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
    {
        var value = JsonSerializer.SerializeToElement(parameters);
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Exact Claude worker parameters required");
        if (Retired) throw new InvalidOperationException("Claude worker was explicitly retired");
        switch (method)
        {
            case "claude/status/read":
                lock (gate)
                {
                    var result = JsonNode.Parse(information.GetRawText())!.AsObject(); result["session_state"] = state;
                    result["worker_pending_requests"] = JsonSerializer.SerializeToNode(native is ClaudeNativeStream liveStream ? liveStream.PendingRequests() : []);
                    var keys = new[] { "claude/remote/" + binding.ThreadId, "claude/launch-handoff/" + binding.ThreadId,
                        LinuxClaudeTopics.RecoveryKey(binding), "claude/switch-checkpoint/" + binding.ThreadId };
                    result["worker_metadata"] = JsonSerializer.SerializeToNode(keys.Where(key => ledger.Get(key) != null).ToDictionary(key => key, key => ledger.Get(key)!.Value));
                    return JsonSerializer.SerializeToElement(result);
                }
            case "claude/remote/read": return remote;
            case "claude/usage/read": return await native.Control("get_usage", value, stop, effect: false);
            case "claude/control":
                var subtype = value.GetProperty("subtype").GetString()!;
                if (subtype is not ("interrupt" or "set_model" or "set_permission_mode" or "set_max_thinking_tokens" or "rewind_files" or "apply_flag_settings"))
                    throw new InvalidDataException("Worker control is outside the native owner protocol");
                return await native.Control(subtype, value.GetProperty("parameters"), stop, value.GetProperty("effect").GetBoolean());
            case "claude/send":
                if (native is not ClaudeNativeStream stream) throw new InvalidDataException("Attested Claude stream required");
                return await stream.SendWithUuid(binding.ThreadId, value.GetProperty("content"), value.GetProperty("uuid").GetString()!, stop);
            case "claude/answer":
                await native.Answer(value.GetProperty("requestId").GetString()!, value.GetProperty("answer"), stop);
                return JsonSerializer.SerializeToElement(new { submitted = true, acknowledged = false });
            case "claude/retire":
                lock (gate) if (state != "idle") throw new InvalidOperationException("An active Claude worker cannot be retired for a switch");
                await native.DisposeAsync(); Retired = true;
                return JsonSerializer.SerializeToElement(new { stopped = true, session = binding.ThreadId });
            default: throw new InvalidDataException("Unsupported Claude worker method");
        }
    }
    public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new NotSupportedException("Use the native Claude request ID via the exact answer method");
    public async ValueTask DisposeAsync() { native.Notification -= Observe; await native.DisposeAsync(); }
}
