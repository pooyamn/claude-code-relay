using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

public sealed record RemoteObservation(string State, uint NativePid, DateTimeOffset? ObservedAt,
    string? InstallationFingerprint, string? EnvironmentFingerprint);

// Read the SAME private app-server used by this router. A different process's
// saved "connected" status cannot establish this thread's phone transport.
// Never enroll/pair, enable a second endpoint, copy credentials, or infer that
// connected means phone acceptance or all-source admission.
public sealed class NativeRemote
{
    private readonly object gate = new();
    private readonly SemaphoreSlim reads = new(1, 1);
    private long revision;
    private RemoteObservation value = new("unavailable", 0, null, null, null);
    public RemoteObservation Snapshot { get { lock (gate) return value; } }

    public void Observe(JsonElement message, uint pid)
    {
        if (message.ValueKind != JsonValueKind.Object || message.TryGetProperty("id", out _) ||
            !message.TryGetProperty("method", out var method) || method.ValueKind != JsonValueKind.String) return;
        if (method.GetString() == "account/updated")
        {
            lock (gate) { revision++; value = new("unavailable", pid, null, null, null); }
        }
        else if (method.GetString() == "remoteControl/status/changed")
        {
            lock (gate)
            {
                revision++;
                try { value = Parse(message.GetProperty("params"), pid, DateTimeOffset.UtcNow); }
                catch (Exception error) when (Invalid(error)) { value = new("unavailable", pid, null, null, null); }
            }
        }
    }

    public async Task Read(INative rpc, CancellationToken stop)
    {
        await reads.WaitAsync(stop);
        long started; lock (gate) started = revision;
        void Updated(JsonElement message) => Observe(message, rpc.Pid);
        rpc.Notification += Updated;
        try
        {
            var result = await rpc.Call("remoteControl/status/read", new { }, stop, effect: false);
            var parsed = Parse(result, rpc.Pid, DateTimeOffset.UtcNow);
            lock (gate) { if (revision == started) { revision++; value = parsed; } }
        }
        catch (Exception error) when (error is NativeRejected or IOException or TimeoutException || Invalid(error))
        {
            lock (gate) { if (revision == started) { revision++; value = new("unavailable", rpc.Pid, null, null, null); } }
        }
        catch (OperationCanceledException)
        {
            lock (gate) { if (revision == started) { revision++; value = new("unavailable", rpc.Pid, null, null, null); } }
            throw;
        }
        finally { rpc.Notification -= Updated; reads.Release(); }
    }

    private static bool Invalid(Exception error) => error is InvalidDataException or InvalidOperationException or KeyNotFoundException or JsonException;
    public static RemoteObservation Parse(JsonElement result, uint pid, DateTimeOffset observedAt)
    {
        if (result.ValueKind != JsonValueKind.Object || pid == 0 ||
            result.EnumerateObject().GroupBy(p => p.Name).Any(g => g.Count() != 1)) throw new InvalidDataException("Invalid native remote status");
        var state = result.GetProperty("status").GetString();
        if (state is not ("disabled" or "connecting" or "connected" or "errored")) throw new InvalidDataException("Unknown native remote state");
        var installation = Identity(result.GetProperty("installationId"));
        var name = result.GetProperty("serverName");
        if (name.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(name.GetString()) ||
            name.GetString()!.Length > 256 || name.GetString()!.Any(char.IsControl)) throw new InvalidDataException("Invalid native remote host name");
        string? environment = null;
        if (result.TryGetProperty("environmentId", out var id) && id.ValueKind != JsonValueKind.Null) environment = Identity(id);
        if (state == "connected" && environment == null) throw new InvalidDataException("Connected native remote has no environment");
        return new(state, pid, observedAt, installation, environment);
    }
    private static string Identity(JsonElement id)
    {
        if (id.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(id.GetString()) ||
            id.GetString()!.Length > 256 || id.GetString()!.Any(char.IsControl)) throw new InvalidDataException("Invalid native remote identity");
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(id.GetString()!)));
    }
    public string Render()
    {
        var observed = Snapshot;
        return "Router's native Remote Control: " + observed.State + " (PID " + observed.NativePid + ").\n" +
            (observed.ObservedAt is { } at ? "Last native observation: " + at.ToString("O") + ".\n" : "No verified native observation.\n") +
            "A separate remote host is not this live connection. Phone round trip and shared admission remain unverified.";
    }
}
