using System.Text.Json;

namespace KhadangRouter;

public interface INative
{
    uint Pid { get; }
    event Action<JsonElement>? Notification;
    Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true);
    Task Reply(JsonElement id, object result, CancellationToken stop);
}
public interface IBot
{
    Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false);
    Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop);
    Task Edit(long chat, int message, string text, CancellationToken stop);
    Task<JsonElement> SendBubble(long chat, int topic, string text, CancellationToken stop) => Send(chat, topic, text, stop);
    Task EditBubble(long chat, int message, string text, CancellationToken stop) => Edit(chat, message, text, stop);
    Task<JsonElement> SendAnswer(long chat, int topic, AnswerPart part, CancellationToken stop) => Send(chat, topic, part.Text, stop);
    Task Download(AttachmentReference file, Stream target, CancellationToken stop) =>
        throw new NotSupportedException("This transport has no attachment download implementation");
}
public sealed class NativeRejected(string method) : Exception("Native explicitly rejected " + method);

// Claude keeps its own protocol. No invented Codex thread/turn RPCs or IDs.
public interface IClaudeNative : IAsyncDisposable
{
    uint Pid { get; }
    string SessionId { get; }
    bool Connected { get; }
    event Action<JsonElement>? Notification;
    Task<JsonElement> Initialize(CancellationToken stop);
    Task<JsonElement> Control(string subtype, object parameters, CancellationToken stop, bool effect = true);
    Task<JsonElement> SendNow(string expectedSessionId, JsonElement content, CancellationToken stop);
    Task Answer(string requestId, object answer, CancellationToken stop);
}
public interface IClaudeTopics
{
    // Must return an already-attested ordinary-owner stream for this exact
    // saved pin/runtime/workspace. The router never discovers a substitute.
    Task<IClaudeNative> Open(Binding binding, CancellationToken stop);
}
