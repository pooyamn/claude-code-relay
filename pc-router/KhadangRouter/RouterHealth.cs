using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    private static bool? Connection(INative? native) => native is INativeConnection health ? health.Connected : null;
    private Task ProbeNativeConnections(CancellationToken stop) => Task.WhenAll(sessions.Values.Where(s => !s.Initializing && s.Claude == null)
        .Select(s => s.Native).OfType<NativeRpc>().Distinct().Select(native => native.CheckLiveness(stop)));

    private bool NativeObserverRestartSafe()
    {
        // Linux sessions and Claude have independent custody. The legacy
        // Windows app-server belongs to this observer: never kill its active
        // work merely to repair another transport.
        var windows = sessions.Values.Where(s => s.Claude == null && s.Binding.Runtime == "windows").ToArray();
        if (windows.Any(s => s.Busy)) return false;
        foreach (var row in ledger.Query("SELECT payload FROM operations WHERE status IN ('attempting','unknown') AND kind LIKE 'native/%'"))
        {
            using var doc = JsonDocument.Parse(row[0]!);
            if (!doc.RootElement.TryGetProperty("parameters", out var parameters) || parameters.ValueKind != JsonValueKind.Object ||
                !parameters.TryGetProperty("threadId", out var thread) || thread.ValueKind != JsonValueKind.String ||
                windows.Any(s => s.Binding.ThreadId == thread.GetString())) return false;
        }
        return true;
    }

    private bool CheckNativeConnections()
    {
        var lost = sessions.Values.Where(s => s.Claude == null && Connection(s.Native) == false)
            .GroupBy(s => s.Binding.Runtime).ToArray();
        var safe = lost.Length != 0 && NativeObserverRestartSafe();
        foreach (var group in lost)
            ledger.Put("native/connection-lost/" + group.Key, new { runtime = group.Key,
                reason = (group.First().Native as INativeConnection)?.DisconnectReason,
                topics = group.Select(s => new { s.Binding.Chat, s.Binding.Topic, s.Binding.ThreadId }),
                state = safe ? "supervised-reattach-no-replay" : "degraded-preserve-owned-windows-work", at = DateTimeOffset.UtcNow });
        return safe;
    }

    private void ObserveCodexSafely(INative source, JsonElement message)
    {
        try { ObserveCodex(source, message); }
        catch (Exception error) when (error is JsonException or InvalidDataException or InvalidOperationException or
            KeyNotFoundException or FormatException or OverflowException or ArgumentException or NullReferenceException)
        {
            // A bad view/schema event must not disconnect the shared RPC reader
            // and strand every topic. Fence only its exact authenticated route;
            // never answer malformed approvals or trust arbitrary payload text.
            Session? target = null;
            if (message.ValueKind == JsonValueKind.Object && message.TryGetProperty("params", out var p) && p.ValueKind == JsonValueKind.Object &&
                p.TryGetProperty("threadId", out var thread) && thread.ValueKind == JsonValueKind.String)
                target = sessions.Values.FirstOrDefault(s => s.Claude == null && ReferenceEquals(s.Native, source) && s.Binding.ThreadId == thread.GetString());
            ledger.Put("native/observer-fault/" + (ReferenceEquals(source, rpc) ? "windows" : "linux"), new {
                errorType = error.GetType().Name, thread = target?.Binding.ThreadId,
                request = message.ValueKind == JsonValueKind.Object && message.TryGetProperty("id", out _), at = DateTimeOffset.UtcNow });
            if (target != null) lock (target.Gate)
            {
                target.Held = true; target.Status = "Held — malformed native event; inspect this topic";
                target.Bubble.Append("\nA native event could not be validated. This topic is held; other topics and the shared transport remain available.\n");
                Touch(target);
            }
        }
    }
}
