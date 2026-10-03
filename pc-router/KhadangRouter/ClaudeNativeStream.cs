using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace KhadangRouter;

// One already-owned Claude stream, not a launcher, broker or Codex emulation.
// The caller must attest the ordinary owner/native image and use --resume with
// the selected pin plus --replay-user-messages. A replay confirms consumption,
// not turn completion. No invented Codex turn ID or reconnect/replay fallback.
public sealed class ClaudeNativeStream : IClaudeNative
{
    public const int MaximumFrameBytes = 2_097_152;
    private readonly INativeChannel channel;
    private readonly Ledger ledger;
    private readonly ConcurrentDictionary<string, TaskCompletionSource<JsonElement>> controls = new();
    private readonly ConcurrentDictionary<string, TaskCompletionSource<JsonElement>> sends = new();
    private readonly ConcurrentDictionary<string, JsonElement> requests = new();
    private readonly object requestGate = new();
    private readonly SemaphoreSlim writes = new(1, 1);
    private readonly CancellationTokenSource stop = new();
    private readonly Task reader;
    private long sequence;
    private int initializationAttempts;
    private volatile bool disconnected, initialized, superseded;
    public event Action<JsonElement>? Notification;
    // Launcher metadata only, never owner or role authentication.
    public uint Pid => channel.Pid;
    public string SessionId { get; }
    public bool Connected => !disconnected;
    public ClaudeNativeStream(INativeChannel channel, Ledger ledger, string sessionId)
    {
        if (!Guid.TryParseExact(sessionId, "D", out _)) throw new InvalidDataException("Exact native Claude session ID required");
        this.channel = channel; this.ledger = ledger; SessionId = sessionId;
        reader = Task.Run(Read);
    }
    public async Task<JsonElement> Initialize(CancellationToken token)
    {
        if (Interlocked.CompareExchange(ref initializationAttempts, 1, 0) != 0)
            throw new InvalidOperationException("Claude initialization already attempted; never replay");
        var result = await Request("initialize", new { hooks = (object?)null }, token, effect: false);
        if (!result.TryGetProperty("session_state", out var state) || state.GetString() is not ("idle" or "running" or "requires_action"))
            throw new InvalidDataException("Native Claude session-state evidence missing");
        lock (requestGate)
        {
            if (superseded) throw new IOException("Claude conversation reset during initialization; reconcile exact native ID");
            initialized = true;
        }
        return result;
    }
    public Task<JsonElement> Control(string subtype, object parameters, CancellationToken token, bool effect = true)
    {
        RequireInitialized();
        if (subtype == "initialize") throw new InvalidOperationException("Use one-shot initialization");
        return Request(subtype, parameters, token, effect);
    }
    private async Task<JsonElement> Request(string subtype, object parameters, CancellationToken token, bool effect)
    {
        if (string.IsNullOrEmpty(subtype) || subtype.Length > 80 || subtype.Any(c => c is not (>= 'a' and <= 'z') and not '_'))
            throw new InvalidDataException("Invalid native Claude control subtype");
        var body = new Dictionary<string, object?> { ["subtype"] = subtype };
        var fields = JsonSerializer.SerializeToElement(parameters);
        if (fields.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Claude control parameters must be an object");
        foreach (var field in fields.EnumerateObject())
            if (!body.TryAdd(field.Name, field.Value.Clone())) throw new InvalidDataException("Duplicate/reserved Claude control parameter");
        var requestId = "khadang-claude-" + Interlocked.Increment(ref sequence);
        var message = Encode(new { type = "control_request", request_id = requestId, request = body });
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (controls.Count >= 64 || !controls.TryAdd(requestId, completion)) throw new InvalidOperationException("Claude control capacity exceeded");
        string? operation = null;
        try
        {
            RequireConnected();
            if (effect) operation = ledger.Attempt("claude/control/" + subtype, new { SessionId, requestId, parameters });
            await Write(message, token, requireInitialized: subtype != "initialize");
            var response = await completion.Task.WaitAsync(TimeSpan.FromSeconds(30), token);
            if (response.GetProperty("subtype").GetString() == "error")
            {
                if (operation != null) ledger.Reject(operation, response);
                throw new NativeRejected("claude/" + subtype);
            }
            var result = response.TryGetProperty("response", out var value) ? value.Clone() : JsonSerializer.SerializeToElement(new { });
            if (operation != null) ledger.Confirm(operation, result);
            return result;
        }
        catch { if (operation != null) ledger.Outcome(operation, "unknown"); throw; }
        finally { controls.TryRemove(requestId, out _); }
    }
    public async Task<JsonElement> SendNow(string expectedSessionId, JsonElement content, CancellationToken token)
    {
        RequireInitialized();
        if (expectedSessionId != SessionId) throw new InvalidDataException("Claude message belongs to another pinned conversation");
        if (content.ValueKind is not (JsonValueKind.String or JsonValueKind.Array)) throw new InvalidDataException("Native Claude content must be text or blocks");
        var uuid = Guid.NewGuid().ToString("D");
        var message = Encode(new { type = "user", message = new { role = "user", content }, origin = new { kind = "human" },
            parent_tool_use_id = (string?)null, session_id = SessionId, uuid, priority = "now" });
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (sends.Count >= 64 || !sends.TryAdd(uuid, completion)) throw new InvalidOperationException("Claude send capacity exceeded");
        string? operation = null;
        try
        {
            operation = ledger.Attempt("claude/user/send-now", new { SessionId, uuid, content });
            await Write(message, token, requireInitialized: true);
            var replay = await completion.Task.WaitAsync(TimeSpan.FromSeconds(30), token);
            ledger.Confirm(operation, JsonSerializer.SerializeToElement(new { SessionId, uuid, receipt = "native-user-replay" }));
            return replay;
        }
        catch { if (operation != null) ledger.Outcome(operation, "unknown"); throw; }
        finally { sends.TryRemove(uuid, out _); }
    }
    // The controller, not this transport, authenticates the human and binds a
    // question/approval to chat, topic and live task before invoking this method.
    public async Task Answer(string requestId, object answer, CancellationToken token)
    {
        RequireInitialized();
        var message = Encode(new { type = "control_response", response = new {
            subtype = "success", request_id = requestId, response = answer } });
        string? operation = null;
        await writes.WaitAsync(token);
        try
        {
            RequireInitialized();
            lock (requestGate)
            {
                if (!requests.TryRemove(requestId, out var original)) throw new InvalidOperationException("Claude request is absent, cancelled or already answered");
                operation = ledger.Attempt("claude/control/answer", new { SessionId, requestId, original, answer });
                ledger.Put(RequestKey(requestId), new { frame = original, status = "answer-attempted" });
            }
            await channel.Write(message, token);
        }
        finally
        {
            // Native control responses have no acknowledgement. Preserve that
            // uncertainty instead of claiming permission acceptance on a write.
            if (operation != null) ledger.Outcome(operation, "unknown");
            writes.Release();
        }
    }
    private string RequestKey(string id) => "claude/request/" + SessionId + "/" + id;
    private bool RememberRequest(JsonElement message)
    {
        if (message.GetProperty("type").GetString() != "control_request" || message.GetProperty("request").ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Malformed native Claude request");
        var id = message.GetProperty("request_id").GetString();
        if (string.IsNullOrEmpty(id) || id.Length > 200) throw new InvalidDataException("Invalid native Claude request ID");
        lock (requestGate)
        {
            var prior = ledger.Get(RequestKey(id));
            if (prior is { } saved)
            {
                if (saved.TryGetProperty("frame", out var original) &&
                    !JsonNode.DeepEquals(JsonNode.Parse(original.GetRawText()), JsonNode.Parse(message.GetRawText())))
                    throw new InvalidDataException("Native Claude request ID changed payload");
                if (saved.GetProperty("status").GetString() != "pending" || requests.ContainsKey(id)) return false;
            }
            if (requests.Count >= 64 || !requests.TryAdd(id, message)) throw new InvalidDataException("Excessive native Claude request");
            ledger.Put(RequestKey(id), new { frame = message, status = "pending" });
            return true;
        }
    }
    private void RequireConnected()
    {
        if (disconnected) throw new IOException("Claude stream disconnected; no replay");
    }
    private void RequireInitialized()
    {
        RequireConnected();
        if (!initialized) throw new InvalidOperationException("Claude stream is not initialized");
    }
    private static string Encode(object value)
    {
        var message = JsonSerializer.Serialize(value);
        if (Encoding.UTF8.GetByteCount(message) > MaximumFrameBytes) throw new InvalidDataException("Claude request too large");
        return message;
    }
    private async Task Write(string message, CancellationToken token, bool requireInitialized = false)
    {
        await writes.WaitAsync(token);
        try
        {
            RequireConnected();
            if (requireInitialized) RequireInitialized();
            await channel.Write(message, token);
        }
        finally { writes.Release(); }
    }
    private async Task Read()
    {
        try
        {
            while (await channel.Read(stop.Token) is { } line)
            {
                if (Encoding.UTF8.GetByteCount(line) > MaximumFrameBytes) throw new InvalidDataException("Claude frame too large");
                using var document = JsonDocument.Parse(line);
                var message = document.RootElement.Clone();
                UniqueKeys(message);
                var kind = message.GetProperty("type").GetString();
                if (kind == "control_response")
                {
                    var response = message.GetProperty("response");
                    var id = response.GetProperty("request_id").GetString();
                    if (string.IsNullOrEmpty(id) || id.Length > 200) throw new InvalidDataException("Invalid Claude response ID");
                    if (response.GetProperty("subtype").GetString() is not ("success" or "error"))
                        throw new InvalidDataException("Malformed native Claude control result");
                    // These arrays are siblings of response, not inside its
                    // success payload. Preserve restored questions without
                    // auto-answering, and deduplicate live/replayed frames.
                    foreach (var name in new[] { "pending_permission_requests", "pending_user_dialog_requests" })
                    {
                        if (!response.TryGetProperty(name, out var snapshot)) continue;
                        if (snapshot.ValueKind != JsonValueKind.Array || snapshot.GetArrayLength() > 64)
                            throw new InvalidDataException("Invalid native Claude pending-request snapshot");
                        foreach (var request in snapshot.EnumerateArray())
                            if (RememberRequest(request.Clone())) Notification?.Invoke(request.Clone());
                    }
                    if (controls.TryGetValue(id, out var completion)) completion.TrySetResult(response.Clone());
                    // A late response is retained as an event, never a fresh
                    // operation receipt or trigger to resubmit the old request.
                    else Notification?.Invoke(message);
                    continue;
                }
                if (kind is "control_request" or "control_cancel_request")
                {
                    var id = message.GetProperty("request_id").GetString();
                    if (string.IsNullOrEmpty(id) || id.Length > 200) throw new InvalidDataException("Invalid native Claude request ID");
                    if (kind == "control_request")
                    {
                        if (!RememberRequest(message)) continue;
                    }
                    else lock (requestGate)
                    {
                        requests.TryRemove(id, out var original);
                        var prior = ledger.Get(RequestKey(id));
                        if (original.ValueKind != JsonValueKind.Undefined) ledger.Put(RequestKey(id), new { frame = original, status = "cancelled" });
                        else if (prior is { } saved && saved.TryGetProperty("frame", out var frame)) ledger.Put(RequestKey(id), new { frame, status = "cancelled" });
                        else ledger.Put(RequestKey(id), new { status = "cancelled" });
                    }
                }
                if (kind == "user" && message.TryGetProperty("uuid", out var uuid) && uuid.ValueKind == JsonValueKind.String &&
                    sends.TryGetValue(uuid.GetString()!, out var send))
                {
                    if (message.GetProperty("session_id").GetString() != SessionId ||
                        message.GetProperty("message").GetProperty("role").GetString() != "user" ||
                        message.GetProperty("parent_tool_use_id").ValueKind != JsonValueKind.Null)
                        throw new InvalidDataException("Claude replay is not the submitted primary-conversation input");
                    send.TrySetResult(message);
                }
                if (kind == "conversation_reset" || kind == "system" && message.TryGetProperty("subtype", out var subtype) && subtype.GetString() == "conversation_reset")
                {
                    // Surface /clear and phone-origin resets. The controller
                    // must reconcile/persist the new native binding; this client
                    // must not keep submitting against its superseded pin.
                    foreach (var waiting in controls.Values.Concat(sends.Values)) waiting.TrySetException(new IOException("Claude conversation reset; reconcile exact native ID"));
                    lock (requestGate)
                    {
                        superseded = true; initialized = false;
                        foreach (var request in requests) ledger.Put(RequestKey(request.Key), new { frame = request.Value, status = "reset" });
                        requests.Clear();
                    }
                }
                Notification?.Invoke(message);
            }
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or JsonException or InvalidDataException or
            InvalidOperationException or KeyNotFoundException or DecoderFallbackException) { }
        finally
        {
            disconnected = true;
            foreach (var pending in controls.Values.Concat(sends.Values)) pending.TrySetException(new IOException("Claude stream disconnected; no replay"));
            requests.Clear();
        }
    }
    private static void UniqueKeys(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var field in element.EnumerateObject())
            { if (!seen.Add(field.Name)) throw new InvalidDataException("Duplicate Claude JSON key"); UniqueKeys(field.Value); }
        }
        else if (element.ValueKind == JsonValueKind.Array)
            foreach (var value in element.EnumerateArray()) UniqueKeys(value);
    }
    public async ValueTask DisposeAsync()
    {
        stop.Cancel();
        try { await Task.WhenAll(reader, channel.DisposeAsync().AsTask()); }
        catch (OperationCanceledException) { }
        finally { stop.Dispose(); writes.Dispose(); }
    }
}
