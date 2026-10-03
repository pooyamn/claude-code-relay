using System.Collections.Concurrent;
using System.Text.Json;

namespace KhadangRouter;

public sealed class NativeRpc : INative, IAsyncDisposable
{
    private readonly WindowsOwnerProcess process;
    private readonly Ledger ledger;
    private readonly ConcurrentDictionary<long, TaskCompletionSource<JsonElement>> pending = new();
    private readonly SemaphoreSlim writes = new(1, 1);
    private readonly CancellationTokenSource stop = new();
    private readonly Task reader, drain;
    private long sequence;
    private volatile bool disconnected;
    public event Action<JsonElement>? Notification;
    public uint Pid => process.Pid;
    public NativeRpc(WindowsOwnerProcess process, Ledger ledger)
    {
        this.process = process; this.ledger = ledger;
        reader = Task.Run(Read);
        drain = Task.Run(async () => { while (await process.Error.ReadLineAsync(stop.Token) != null) { /* Never mirror native diagnostics containing credentials. */ } });
    }
    public async Task Initialize(CancellationToken token)
    {
        await Call("initialize", new { clientInfo = new { name = "khadang-pc-router", title = "Khadang PC", version = "0.1.0" },
            capabilities = new { experimentalApi = true } }, token, effect: false);
        await Write(new { method = "initialized", @params = new { } }, token);
    }
    public async Task<JsonElement> Call(string method, object parameters, CancellationToken token, bool effect = true)
    {
        if (disconnected) throw new IOException("Native stream disconnected; no replay");
        var id = Interlocked.Increment(ref sequence);
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!pending.TryAdd(id, completion)) throw new InvalidOperationException("RPC ID collision");
        var operation = effect ? ledger.Attempt("native/" + method, new { id, parameters }) : null;
        try
        {
            await Write(new { id, method, @params = parameters }, token);
            var response = await completion.Task.WaitAsync(TimeSpan.FromSeconds(30), token);
            if (response.TryGetProperty("error", out var error))
            {
                if (operation != null) ledger.Reject(operation, error);
                throw new NativeRejected(method);
            }
            var result = response.GetProperty("result").Clone();
            if (operation != null) ledger.Confirm(operation, result);
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
    private async Task Write(object message, CancellationToken token)
    {
        await writes.WaitAsync(token);
        try { await process.Input.WriteLineAsync(JsonSerializer.Serialize(message).AsMemory(), token); }
        finally { writes.Release(); }
    }
    private async Task Read()
    {
        try
        {
            while (await process.Output.ReadLineAsync(stop.Token) is { } line)
            {
                if (line.Length > 2_097_152) throw new InvalidDataException("Native frame too large");
                using var document = JsonDocument.Parse(line);
                var message = document.RootElement.Clone();
                if (!message.TryGetProperty("method", out _) && message.TryGetProperty("id", out var id) &&
                    id.ValueKind == JsonValueKind.Number && id.TryGetInt64(out var number) && pending.TryGetValue(number, out var completion)) completion.TrySetResult(message);
                else Notification?.Invoke(message);
            }
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or JsonException or InvalidDataException or InvalidOperationException or KeyNotFoundException) { }
        finally { disconnected = true; foreach (var request in pending.Values) request.TrySetException(new IOException("Native stream disconnected; no replay")); }
    }
    public async ValueTask DisposeAsync()
    {
        stop.Cancel(); process.Dispose();
        try { await Task.WhenAll(reader, drain); } catch (OperationCanceledException) { }
        stop.Dispose(); writes.Dispose();
    }
}
