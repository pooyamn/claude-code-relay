using System.Buffers.Binary;
using System.IO.Pipes;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace KhadangRouter;

// Candidate protected component protocol, not worker/company authentication or
// model admission. The launcher supplies both exact peer pins and broker epoch;
// no self-asserted PID, discovery fallback, native initialization or reconnect.
public sealed record BrokerWireRequest(int Protocol, string Id, string Kind, string Epoch,
    string? Intent = null, string? Method = null, JsonElement? Parameters = null,
    long? Cursor = null, int? Maximum = null, string? After = null,
    BrokerWireReview? Reviewed = null, JsonElement? Result = null);
public sealed record BrokerWireReview(string Epoch, JsonElement Id, string? Thread,
    string? Turn, string Fingerprint, string Frame)
{
    internal BrokerRequest Native()
    {
        if (Frame == null || Encoding.UTF8.GetByteCount(Frame) > WebSocketNativeChannel.MaximumFrameBytes)
            throw new InvalidDataException("Complete bounded reviewed frame required");
        using var parsed = JsonDocument.Parse(Frame);
        if (parsed.RootElement.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Native request object required");
        return new(Epoch, Id, Thread, Turn, Fingerprint, parsed.RootElement.Clone());
    }
    internal static BrokerWireReview From(BrokerRequest request) => new(request.Epoch,
        request.Id, request.Thread, request.Turn, request.Fingerprint, request.Frame.GetRawText());
}
internal sealed record BrokerWireResponse(int Protocol, string Id, string Epoch, string Status, JsonElement? Data);
public sealed record BrokerWireStatus(string Epoch, uint Pid, long Position);
public sealed record BrokerWireEvent(long Position, string Frame);

internal static class BrokerWireFrames
{
    // A complete native frame carried as JSON text may escape to twice its byte
    // size; a reviewed reply may additionally carry a full-size native result.
    internal const int MaximumBytes = 3 * WebSocketNativeChannel.MaximumFrameBytes + 16384;
    internal static readonly JsonSerializerOptions Json = new() {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
    };
    internal static async Task<JsonElement?> Read(Stream stream, CancellationToken stop)
    {
        var header = new byte[4];
        if (await stream.ReadAsync(header.AsMemory(0, 1), stop) == 0) return null;
        await stream.ReadExactlyAsync(header.AsMemory(1), stop);
        var size = BinaryPrimitives.ReadInt32BigEndian(header);
        if (size is < 2 or > MaximumBytes) throw new InvalidDataException("Broker frame size refused");
        var bytes = new byte[size]; await stream.ReadExactlyAsync(bytes, stop);
        using var parsed = JsonDocument.Parse(bytes);
        if (parsed.RootElement.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Broker object required");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in parsed.RootElement.EnumerateObject())
            if (!names.Add(property.Name)) throw new InvalidDataException("Duplicate broker envelope field");
        return parsed.RootElement.Clone();
    }
    internal static async Task Write(Stream stream, object value, SemaphoreSlim writes, CancellationToken stop,
        CancellationToken beforeWrite = default)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(value, Json);
        if (bytes.Length > MaximumBytes) throw new InvalidDataException("Broker response exceeds complete-frame bound");
        var header = new byte[4]; BinaryPrimitives.WriteInt32BigEndian(header, bytes.Length);
        using var waiting = CancellationTokenSource.CreateLinkedTokenSource(stop, beforeWrite);
        await writes.WaitAsync(waiting.Token);
        try
        {
            // A canceled caller waiting for the write lock submits nothing.
            // Once a frame starts, only connection loss cancels its write.
            beforeWrite.ThrowIfCancellationRequested();
            await stream.WriteAsync(header, stop); await stream.WriteAsync(bytes, stop); await stream.FlushAsync(stop);
        }
        finally { writes.Release(); }
    }
}

public static class NativeBrokerWire
{
    // Authorization is mandatory, reviewed caller-owned policy, not a default
    // allow-all handler. Company/root/admission/approval integration is separate.
    public static async Task Serve(NativeBroker broker, NamedPipeServerStream stream,
        WindowsPipePin expectedClient, string protectedRoot, Action<BrokerWireRequest> authorize,
        CancellationToken stop)
    {
        using var peer = WindowsPipePeer.Authenticate(stream, false, expectedClient, protectedRoot);
        using var attached = broker.Attach(peer);
        await ServeAttached(attached, stream, authorize, stop);
    }
    internal static async Task ServeAttached(NativeBrokerSession attached, Stream stream,
        Action<BrokerWireRequest> authorize, CancellationToken stop)
    {
        ArgumentNullException.ThrowIfNull(authorize);
        using var connection = CancellationTokenSource.CreateLinkedTokenSource(stop);
        using var writes = new SemaphoreSlim(1, 1);
        var active = new Dictionary<string, Task>(StringComparer.Ordinal);
        try
        {
            while (await BrokerWireFrames.Read(stream, connection.Token) is { } message)
            {
                var request = message.Deserialize<BrokerWireRequest>(BrokerWireFrames.Json)
                    ?? throw new InvalidDataException("Broker request required");
                // Nullable DTOs collapse explicit JSON null and a missing field.
                // Preserve null as an actual native reply result, not an omission.
                if (message.TryGetProperty("Result", out var result)) request = request with { Result = result.Clone() };
                if (request.Protocol != 1 || !Guid.TryParseExact(request.Id, "N", out _) || request.Epoch != attached.Epoch)
                    throw new InvalidDataException("Pinned protocol, request and native epoch required");
                foreach (var id in active.Where(pair => pair.Value.IsCompleted).Select(pair => pair.Key).ToArray())
                { await active[id]; active.Remove(id); }
                if (active.Count >= 32 || active.ContainsKey(request.Id)) throw new InvalidDataException("Bounded unique in-flight requests required");
                active.Add(request.Id, Task.Run(async () => {
                    BrokerWireResponse response;
                    try
                    {
                        // Current peer + native custody are checked before policy
                        // and again by the effect/event/reply entry points.
                        await attached.Status(connection.Token);
                        ValidateShape(request); authorize(request);
                        var result = await Dispatch(attached, request, connection.Token);
                        response = new(1, request.Id, attached.Epoch, "confirmed", result);
                    }
                    catch (NativeRejected) { response = new(1, request.Id, attached.Epoch, "rejected", null); }
                    catch (Exception error) when (error is InvalidDataException or ArgumentException or JsonException)
                    { response = new(1, request.Id, attached.Epoch, "refused", null); }
                    catch (UnauthorizedAccessException) { response = new(1, request.Id, attached.Epoch, "refused", null); }
                    catch (Exception error) when (error is IOException or InvalidOperationException or TimeoutException)
                    { response = new(1, request.Id, attached.Epoch, "unconfirmed", null); }
                    catch { connection.Cancel(); throw; }
                    try { await BrokerWireFrames.Write(stream, response, writes, connection.Token); }
                    catch { connection.Cancel(); throw; }
                }));
            }
        }
        finally
        {
            // This cancels connection waiters only. Broker-registered native
            // calls/replies continue under its own lifetime and private journal.
            connection.Cancel();
            try { await Task.WhenAll(active.Values); }
            catch (Exception error) when (error is IOException or OperationCanceledException or InvalidDataException or ObjectDisposedException) { }
        }
    }
    private static void ValidateShape(BrokerWireRequest request)
    {
        var call = request.Kind == "call"; var events = request.Kind == "events";
        var requests = request.Kind == "requests"; var reply = request.Kind == "reply";
        if (request.Kind is not ("status" or "call" or "events" or "requests" or "reply") ||
            call != (request.Intent != null && request.Method != null && request.Parameters != null) ||
            !call && (request.Intent != null || request.Method != null || request.Parameters != null) ||
            events != request.Cursor.HasValue || (events || requests) != request.Maximum.HasValue ||
            !requests && request.After != null || request.After is { Length: > 1024 } ||
            reply != (request.Reviewed != null && request.Result != null) ||
            !reply && (request.Reviewed != null || request.Result != null) ||
            request.Maximum is < 1 or > 100)
            throw new InvalidDataException("Exact broker operation shape required");
    }
    private static async Task<JsonElement> Dispatch(NativeBrokerSession attached, BrokerWireRequest request, CancellationToken stop)
    {
        switch (request.Kind)
        {
            case "status": return JsonSerializer.SerializeToElement(await attached.Status(stop));
            case "call": return await attached.Call(request.Intent!, request.Method!, request.Parameters!.Value, stop);
            case "events":
                return Pack(attached.Events(request.Cursor!.Value, request.Maximum!.Value)
                    .Select(e => new BrokerWireEvent(e.Position, e.Frame.GetRawText())));
            case "requests":
                return Pack(attached.Requests().OrderBy(r => r.Id.GetRawText(), StringComparer.Ordinal)
                    .Where(r => request.After == null || string.CompareOrdinal(r.Id.GetRawText(), request.After) > 0)
                    .Take(request.Maximum!.Value).Select(BrokerWireReview.From));
            case "reply":
                await attached.Reply(request.Reviewed!.Native(), request.Result!.Value).WaitAsync(stop);
                // Confirmed means the broker observed a write, NOT approval
                // acceptance or completion. Native resolution is separate.
                return JsonSerializer.SerializeToElement(new { written = true, accepted = false });
            default: throw new InvalidDataException("Unknown broker operation");
        }
    }
    private static JsonElement Pack<T>(IEnumerable<T> source)
    {
        var result = new List<T>(); var size = 1024;
        foreach (var item in source)
        {
            var length = JsonSerializer.SerializeToUtf8Bytes(item, BrokerWireFrames.Json).Length + 1;
            if (size + length > BrokerWireFrames.MaximumBytes)
            {
                if (result.Count == 0) throw new InvalidDataException("Complete broker item exceeds page bound");
                break; // Caller advances only through the items actually returned.
            }
            result.Add(item); size += length;
        }
        return JsonSerializer.SerializeToElement(result, BrokerWireFrames.Json);
    }
}

// Explicit stable intents: the trusted router must persist them before calling.
// This client never issues initialize/initialized, starts a native process or
// retries a failed/ambiguous request. It owns ONLY its attached transport.
public sealed class NativeBrokerWireClient : IAsyncDisposable
{
    private readonly Stream stream;
    private readonly WindowsPipePeer? peer;
    private readonly string epoch;
    private readonly CancellationTokenSource stop = new();
    private readonly SemaphoreSlim writes = new(1, 1);
    private readonly object gate = new();
    private readonly Dictionary<string, TaskCompletionSource<JsonElement>> pending = new(StringComparer.Ordinal);
    private readonly Task reader;
    private bool disconnected, disposed;
    private int writing;
    private TaskCompletionSource? writesDrained;
    private Task? shutdown;
    public static async Task<NativeBrokerWireClient> Connect(string endpoint, WindowsPipePin server,
        string epoch, string protectedRoot, CancellationToken stop)
    {
        var (stream, peer) = await WindowsPipePeer.Connect(endpoint, server, protectedRoot, stop);
        try { return new(stream, peer, epoch); } catch { peer.Dispose(); stream.Dispose(); throw; }
    }
    private NativeBrokerWireClient(Stream stream, WindowsPipePeer? peer, string epoch)
    {
        if (!Guid.TryParseExact(epoch, "N", out _)) throw new InvalidDataException("Pinned native epoch required");
        this.stream = stream; this.peer = peer; this.epoch = epoch; reader = Task.Run(Read);
    }
    internal static NativeBrokerWireClient Fixture(Stream stream, string epoch) => new(stream, null, epoch);
    public async Task<BrokerWireStatus> Status(CancellationToken stop)
    {
        var status = (await Exchange(new(1, Id(), "status", epoch), stop)).Deserialize<BrokerWireStatus>(BrokerWireFrames.Json);
        if (status == null || status.Epoch != epoch || status.Pid == 0 || status.Position < 0)
            throw new InvalidDataException("Pinned broker status required");
        return status;
    }
    public Task<JsonElement> Call(string intent, string method, object parameters, CancellationToken stop) =>
        Exchange(new(1, Id(), "call", epoch, Intent: intent, Method: method,
            Parameters: JsonSerializer.SerializeToElement(parameters)), stop);
    public async Task<IReadOnlyList<BrokerEvent>> Events(long cursor, int maximum, CancellationToken stop)
    {
        var page = (await Exchange(new(1, Id(), "events", epoch, Cursor: cursor, Maximum: maximum), stop))
            .Deserialize<BrokerWireEvent[]>(BrokerWireFrames.Json) ?? throw new InvalidDataException("Broker events missing");
        if (page.Length > maximum) throw new InvalidDataException("Broker event page exceeds requested bound");
        var events = new List<BrokerEvent>();
        foreach (var item in page)
        {
            if (item == null || item.Position != checked(++cursor) || item.Frame == null ||
                Encoding.UTF8.GetByteCount(item.Frame) > WebSocketNativeChannel.MaximumFrameBytes)
                throw new InvalidDataException("Complete contiguous broker event required");
            using var parsed = JsonDocument.Parse(item.Frame);
            if (parsed.RootElement.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Native event object required");
            events.Add(new(epoch, cursor, parsed.RootElement.Clone()));
        }
        return events;
    }
    public async Task<IReadOnlyList<BrokerRequest>> Requests(string? after, int maximum, CancellationToken stop)
    {
        var page = (await Exchange(new(1, Id(), "requests", epoch, After: after, Maximum: maximum), stop))
            .Deserialize<BrokerWireReview[]>(BrokerWireFrames.Json) ?? throw new InvalidDataException("Broker requests missing");
        if (page.Length > maximum) throw new InvalidDataException("Broker request page exceeds requested bound");
        var result = new List<BrokerRequest>();
        foreach (var item in page)
        {
            if (item == null || item.Epoch != epoch || string.IsNullOrEmpty(item.Thread) ||
                after != null && string.CompareOrdinal(item.Id.GetRawText(), after) <= 0)
                throw new InvalidDataException("Pinned ordered thread request required");
            result.Add(item.Native()); after = item.Id.GetRawText();
        }
        return result;
    }
    public Task<JsonElement> Reply(BrokerRequest reviewed, object result, CancellationToken stop) =>
        Exchange(new(1, Id(), "reply", epoch, Reviewed: BrokerWireReview.From(reviewed),
            Result: JsonSerializer.SerializeToElement(result)), stop);
    private static string Id() => Guid.NewGuid().ToString("N");
    private async Task<JsonElement> Exchange(BrokerWireRequest request, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (gate)
        {
            Current();
            if (pending.Count >= 32) throw new InvalidOperationException("Broker client outstanding bound reached");
            pending.Add(request.Id, completion);
            if (writing++ == 0) writesDrained = new(TaskCreationOptions.RunContinuationsAsynchronously);
        }
        try { await BrokerWireFrames.Write(stream, request, writes, stop.Token, token); }
        catch (OperationCanceledException) when (token.IsCancellationRequested && !stop.IsCancellationRequested)
        { lock (gate) pending.Remove(request.Id); throw; }
        catch { Disconnect(); throw; }
        finally { lock (gate) if (--writing == 0) writesDrained!.TrySetResult(); }
        // Caller cancellation never cancels a submitted native action. Keep
        // the correlation until the stream's actual response/disconnect arrives.
        return await completion.Task.WaitAsync(token);
    }
    private void Current()
    { if (disconnected || disposed) throw new IOException("Broker transport disconnected; no reconnect or replay"); peer?.Current(); }
    private async Task Read()
    {
        try
        {
            while (await BrokerWireFrames.Read(stream, stop.Token) is { } frame)
            {
                var response = frame.Deserialize<BrokerWireResponse>(BrokerWireFrames.Json)
                    ?? throw new InvalidDataException("Broker response required");
                var hasData = frame.TryGetProperty("Data", out var data);
                TaskCompletionSource<JsonElement> completion;
                lock (gate)
                {
                    Current();
                    // Validate the complete envelope BEFORE removing its waiter.
                    // A malformed reply must not strand that request forever.
                    if (response.Protocol != 1 || response.Epoch != epoch || !Guid.TryParseExact(response.Id, "N", out _) ||
                        response.Status is not ("confirmed" or "rejected" or "refused" or "unconfirmed") ||
                        (response.Status == "confirmed") != hasData || !pending.Remove(response.Id, out completion!))
                        throw new InvalidDataException("Unexpected broker response identity or outcome");
                }
                if (response.Status == "confirmed") completion.TrySetResult(data.Clone());
                else if (response.Status == "rejected") completion.TrySetException(new NativeRejected("broker call"));
                else if (response.Status == "refused") completion.TrySetException(new InvalidDataException("Broker refused operation; no automatic replacement"));
                else completion.TrySetException(new IOException("Broker operation unconfirmed; inspect stable intent, never replay"));
            }
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or JsonException or InvalidDataException or ObjectDisposedException) { }
        finally { Disconnect(); }
    }
    private void Disconnect()
    {
        lock (gate)
        {
            if (disconnected) return;
            disconnected = true;
            foreach (var request in pending.Values) request.TrySetException(new IOException("Broker disconnected; inspect stable intent, never replay"));
            pending.Clear();
        }
        stop.Cancel(); stream.Dispose(); // Only the client's transport, never native custody.
    }
    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            if (shutdown != null) return new(shutdown);
            disposed = true;
            shutdown = Task.Run(async () => {
                Disconnect(); Task drain; lock (gate) drain = writesDrained?.Task ?? Task.CompletedTask;
                try { await Task.WhenAll(reader, drain); }
                finally { peer?.Dispose(); stop.Dispose(); writes.Dispose(); }
            });
            return new(shutdown);
        }
    }
}
