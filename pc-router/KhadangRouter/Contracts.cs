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
    Task Download(AttachmentReference file, Stream target, CancellationToken stop) =>
        throw new NotSupportedException("This transport has no attachment download implementation");
}
public sealed class NativeRejected(string method) : Exception("Native explicitly rejected " + method);
