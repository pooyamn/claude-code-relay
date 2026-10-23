using System.Collections.Concurrent;
using System.Text.Json;
using System.Text;

namespace KhadangRouter;

// Availability only, never native identity or authority to retry an action.
public interface INativeConnection { bool Connected { get; } string? DisconnectReason { get; } }
public sealed class NativeNotSubmitted() : IOException("Native transport unavailable before dispatch; no input sent");

public sealed class NativeRpc : INative, INativeConnection, IAsyncDisposable
{
    private readonly INativeChannel channel;
    private readonly Ledger ledger;
    private readonly ConcurrentDictionary<long, TaskCompletionSource<JsonElement>> pending = new();
    private readonly SemaphoreSlim writes = new(1, 1);
    private readonly CancellationTokenSource stop = new();
    private readonly Task reader;
    private long sequence;
    private int initializationAttempts;
    private volatile bool disconnected;
    private string? disconnectReason;
    private long lastRoundTripUnixMs;
    internal TimeSpan ReplyTimeout { get; init; } = TimeSpan.FromSeconds(30);
    public event Action<JsonElement>? Notification;
    public uint Pid => channel.Pid;
    public bool Connected => !disconnected;
    public string? DisconnectReason => disconnectReason;
    public DateTimeOffset? LastRoundTripAt => Interlocked.Read(ref lastRoundTripUnixMs) is var stamp && stamp != 0 ? DateTimeOffset.FromUnixTimeMilliseconds(stamp) : null;
    public int InitializationAttempts => Volatile.Read(ref initializationAttempts);
    public NativeRpc(WindowsOwnerProcess process, Ledger ledger) : this(new StdioNativeChannel(process), ledger) { }
    public NativeRpc(INativeChannel channel, Ledger ledger)
    {
        this.channel = channel; this.ledger = ledger;
        reader = Task.Run(Read);
    }
    public async Task Initialize(CancellationToken token)
    {
        if (Interlocked.CompareExchange(ref initializationAttempts, 1, 0) != 0)
            throw new InvalidOperationException("Native transport initialization already attempted; never replay");
        await Call("initialize", new { clientInfo = new { name = "khadang-pc-router", title = "Khadang PC", version = "0.1.0" },
            capabilities = new { experimentalApi = true } }, token, effect: false);
        await Write(new { method = "initialized", @params = new { } }, token);
    }
    public async Task<JsonElement> Call(string method, object parameters, CancellationToken token, bool effect = true)
    {
        // This check precedes both the durable mutation intent AND the write.
        // Only this proven pre-dispatch failure may avoid a sticky input hold.
        if (disconnected) throw new NativeNotSubmitted();
        var id = Interlocked.Increment(ref sequence);
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!pending.TryAdd(id, completion)) throw new InvalidOperationException("RPC ID collision");
        var operation = effect ? ledger.Attempt("native/" + method, new { id, parameters }) : null;
        try
        {
            await Write(new { id, method, @params = parameters }, token);
            var response = await completion.Task.WaitAsync(ReplyTimeout, token);
            Interlocked.Exchange(ref lastRoundTripUnixMs, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            if (response.TryGetProperty("error", out var error))
            {
                if (operation != null) ledger.Reject(operation, error);
                throw new NativeRejected(method);
            }
            var result = response.GetProperty("result").Clone();
            if (operation != null) { ledger.Confirm(operation, result); ledger.ReconcileInputReceipt(operation); }
            return result;
        }
        catch
        {
            if (operation != null) ledger.Outcome(operation, "unknown");
            throw;
        }
        finally { pending.TryRemove(id, out _); }
    }
    public async Task Reply(JsonElement id, object result, CancellationToken token) => await Write(new { id, result }, token);
    internal async Task CheckLiveness(CancellationToken token)
    {
        if (!Connected || LastRoundTripAt is { } seen && DateTimeOffset.UtcNow - seen < TimeSpan.FromMinutes(1)) return;
        try { await Call("thread/loaded/list", new { }, token, effect: false); }
        catch (NativeRejected)
        { /* An explicit rejection still proves this authenticated link replied. */ }
        catch (Exception error) when (error is IOException or TimeoutException)
        {
            // A read-only probe has no mutation to replay or acknowledge. Stop
            // new writes; the normal observer/supervisor path reattaches only
            // where independent custody or idle Windows work makes it safe.
            disconnectReason = "ReadProbe" + error.GetType().Name; disconnected = true;
        }
    }
    private async Task Write(object message, CancellationToken token)
    {
        await writes.WaitAsync(token);
        try { await channel.Write(JsonSerializer.Serialize(message), token); }
        finally { writes.Release(); }
    }
    private async Task Read()
    {
        try
        {
            while (await channel.Read(stop.Token) is { } line)
            {
                if (line.Length > 2_097_152) throw new InvalidDataException("Native frame too large");
                using var document = JsonDocument.Parse(line);
                var message = document.RootElement.Clone();
                if (!message.TryGetProperty("method", out _) && message.TryGetProperty("id", out var id) &&
                    id.ValueKind == JsonValueKind.Number && id.TryGetInt64(out var number) && pending.TryGetValue(number, out var completion)) completion.TrySetResult(message);
                else Notification?.Invoke(message);
            }
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or JsonException or InvalidDataException or InvalidOperationException or KeyNotFoundException or DecoderFallbackException)
        { disconnectReason = error.GetType().Name; }
        finally { disconnectReason ??= "EndOfStream"; disconnected = true; foreach (var request in pending.Values) request.TrySetException(new IOException("Native stream disconnected; no replay")); }
    }
    public async ValueTask DisposeAsync()
    {
        stop.Cancel();
        try { await Task.WhenAll(reader, channel.DisposeAsync().AsTask()); }
        catch (OperationCanceledException) { }
        finally { stop.Dispose(); writes.Dispose(); }
    }
}
