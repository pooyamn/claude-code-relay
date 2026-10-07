using System.Text.Json;

namespace KhadangRouter;

// Native SDK 0.3.288 control contract, measured against Claude 2.1.288.
// Enable the ALREADY owned stream, never attach a second worker or create/fork
// a local conversation. A cloud session ID is a mapping, not a native UUID.
internal static class ClaudeRemoteControl
{
    internal sealed record Receipt(string BridgeSessionId, string SessionUrl);
    internal static Receipt Parse(JsonElement value)
    {
        if (!value.TryGetProperty("bridge_session_id", out var id) || id.ValueKind != JsonValueKind.String ||
            id.GetString() is not { Length: > 0 and <= 200 } bridge || bridge.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not '_' and not '-') ||
            !value.TryGetProperty("session_url", out var url) || url.ValueKind != JsonValueKind.String ||
            url.GetString() is not { Length: > 0 and <= 2048 } link || !Uri.TryCreate(link, UriKind.Absolute, out var uri) ||
            uri.Scheme != "https" || uri.Host != "claude.ai" || !uri.IsDefaultPort || uri.UserInfo.Length != 0 ||
            !uri.AbsolutePath.StartsWith("/code/", StringComparison.Ordinal) || uri.AbsolutePath.Length <= 6 || uri.Fragment.Length != 0)
            throw new InvalidDataException("Native Claude Remote Control enrollment identity/URL missing");
        return new(bridge, link);
    }
    internal static async Task<Receipt> Enable(IClaudeNative native, Binding binding, Ledger ledger, CancellationToken stop)
    {
        if (binding.Backend != "claude" || binding.Runtime != "linux" || native.SessionId != binding.ThreadId || !native.Connected)
            throw new InvalidDataException("Remote Control requires the exact already-owned Claude conversation");
        var key = "claude/remote/" + binding.ThreadId;
        var previous = ledger.Get(key);
        if (previous is { } saved && saved.GetProperty("phase").GetString() is "attempting" or "unknown")
            throw new InvalidOperationException("Remote Control enrollment is uncertain; reconcile, never repeat");
        Receipt? prior = previous is { } p && p.GetProperty("phase").GetString() == "ready" ?
            JsonSerializer.Deserialize<Receipt>(p.GetProperty("receipt")) : null;
        if (native is ClaudeWorkerClient worker)
        {
            var current = Parse(await worker.Remote(stop));
            if (prior != null && prior != current) throw new InvalidDataException("Persistent worker changed the saved cloud session");
            if (prior == null) ledger.Put(key, new { phase = "ready", binding.ThreadId, receipt = current, at = DateTimeOffset.UtcNow });
            return current; // Read the live host's cached receipt; no native registration.
        }
        if (ledger.Unknown != 0) throw new InvalidOperationException("Remote Control held by uncertain effects");
        var request = new Dictionary<string, object?> { ["enabled"] = true, ["name"] = binding.Name, ["keep_session_on_exit"] = true };
        if (prior != null)
        {
            Parse(JsonSerializer.SerializeToElement(new { bridge_session_id = prior.BridgeSessionId, session_url = prior.SessionUrl }));
            request["reattach_session_id"] = prior.BridgeSessionId;
        }
        // Durable intent precedes the native side effect, even if the router
        // dies before the transport writes its own operation journal.
        ledger.Put(key, new { phase = "attempting", binding.ThreadId, previous = prior, at = DateTimeOffset.UtcNow });
        try
        {
            var receipt = Parse(await native.Control("remote_control", request, stop));
            if (prior != null && receipt.BridgeSessionId != prior.BridgeSessionId)
                throw new InvalidDataException("Native Remote Control substituted the saved cloud mapping");
            ledger.Put(key, new { phase = "ready", binding.ThreadId, receipt, at = DateTimeOffset.UtcNow });
            return receipt; // Registration, not proof a phone has connected.
        }
        catch (NativeRejected)
        { ledger.Put(key, new { phase = "rejected", binding.ThreadId, previous = prior, at = DateTimeOffset.UtcNow }); throw; }
        catch
        { ledger.Put(key, new { phase = "unknown", binding.ThreadId, previous = prior, at = DateTimeOffset.UtcNow }); throw; }
    }
}
