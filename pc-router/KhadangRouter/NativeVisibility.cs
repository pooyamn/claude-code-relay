using System.Text.Json;

namespace KhadangRouter;

public sealed record ThreadListObservation(bool Found, bool Exhausted, int Pages);
public sealed record ThreadVisibilityObservation(string State, string ThreadId, uint NativePid, string? Source,
    ThreadListObservation? DefaultSources, ThreadListObservation? AppServerSource, DateTimeOffset At);

// Diagnostic only: read persisted metadata without resuming/subscribing to a
// live thread owned by another app-server. Never mirror history/preview/cwd,
// repair SQLite from rollouts, start inference, or change a thread's source.
public static class NativeVisibility
{
    public static async Task<ThreadVisibilityObservation> Read(INative rpc, Binding binding, CancellationToken stop)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stop);
        deadline.CancelAfter(TimeSpan.FromSeconds(45));
        try
        {
            var reply = await rpc.Call("thread/read", new { threadId = binding.ThreadId, includeTurns = false }, deadline.Token, effect: false);
            var thread = reply.GetProperty("thread");
            if (thread.GetProperty("id").GetString() != binding.ThreadId ||
                !string.Equals(thread.GetProperty("cwd").GetString(), binding.Workspace, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Native visibility thread/workspace mismatch");
            var source = thread.GetProperty("source");
            var kind = source.ValueKind == JsonValueKind.String && source.GetString() is "cli" or "vscode" or "exec" or "appServer" or "unknown"
                ? source.GetString() : "other";
            var defaults = await List(rpc, binding, false, deadline.Token);
            var appServer = await List(rpc, binding, true, deadline.Token);
            return new("observed", binding.ThreadId, rpc.Pid, kind, defaults, appServer, DateTimeOffset.UtcNow);
        }
        catch (Exception error) when (error is NativeRejected or IOException or TimeoutException or InvalidDataException or
            InvalidOperationException or KeyNotFoundException or JsonException || error is OperationCanceledException && !stop.IsCancellationRequested)
        { return new("unavailable", binding.ThreadId, rpc.Pid, null, null, null, DateTimeOffset.UtcNow); }
    }
    private static async Task<ThreadListObservation> List(INative rpc, Binding binding, bool appServer, CancellationToken stop)
    {
        string? cursor = null;
        var seen = new HashSet<string>();
        for (int page = 1; page <= 2; page++)
        {
            var parameters = new Dictionary<string, object?> { ["cwd"] = binding.Workspace, ["limit"] = 100, ["useStateDbOnly"] = true };
            if (cursor != null) parameters["cursor"] = cursor;
            if (appServer) parameters["sourceKinds"] = new[] { "appServer" };
            var reply = await rpc.Call("thread/list", parameters, stop, effect: false);
            var data = reply.GetProperty("data");
            if (data.ValueKind != JsonValueKind.Array || data.GetArrayLength() > 100) throw new InvalidDataException("Invalid native visibility page");
            bool found = data.EnumerateArray().Any(t => t.GetProperty("id").GetString() == binding.ThreadId);
            var next = reply.GetProperty("nextCursor");
            if (next.ValueKind == JsonValueKind.Null) return new(found, true, page);
            cursor = next.GetString();
            if (string.IsNullOrWhiteSpace(cursor) || cursor.Length > 2048 || !seen.Add(cursor)) throw new InvalidDataException("Invalid native visibility cursor");
            if (found) return new(true, false, page);
        }
        // A bounded/truncated listing is not evidence of absence.
        return new(false, false, 2);
    }
}
