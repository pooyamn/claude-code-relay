using System.Text.Json;

namespace KhadangRouter;

// A disabled route, NOT a native connection. Keeping its backend explicit
// prevents any null-adapter path from sending a Claude topic to Codex.
internal sealed class UnavailableClaude(string sessionId) : IClaudeNative
{
    public uint Pid => 0;
    public string SessionId => sessionId;
    public bool Connected => false;
    public event Action<JsonElement>? Notification { add { } remove { } }
    private static IOException Held() => new("Exact Claude worker is unavailable; no replacement or replay");
    public Task<JsonElement> Initialize(CancellationToken stop) => throw Held();
    public Task<JsonElement> Control(string subtype, object parameters, CancellationToken stop, bool effect = true) => throw Held();
    public Task<JsonElement> SendNow(string expectedSessionId, JsonElement content, CancellationToken stop) => throw Held();
    public Task Answer(string requestId, object answer, CancellationToken stop) => throw Held();
    public ValueTask RetireForSwitch(CancellationToken stop) => throw Held();
    public ValueTask DisposeAsync() => ValueTask.CompletedTask;
}
