using System.Net.WebSockets;
using System.Text;

namespace KhadangRouter;

// Framing only, NOT peer/role authentication or a deployment grant. Production
// still constructs the existing owned stdio channel. A shared connection needs
// a separately reviewed launcher/server-authentication/lease boundary; a PID,
// connected socket, loopback address or client bearer is not that boundary.
public interface INativeChannel : IAsyncDisposable
{
    uint Pid { get; }
    Task<string?> Read(CancellationToken stop);
    Task Write(string message, CancellationToken stop);
}

internal sealed class StdioNativeChannel : INativeChannel
{
    private readonly WindowsOwnerProcess process;
    private readonly CancellationTokenSource stop = new();
    private readonly Task drain;
    public uint Pid => process.Pid;
    public StdioNativeChannel(WindowsOwnerProcess process)
    {
        this.process = process;
        drain = Task.Run(async () => {
            while (await process.Error.ReadLineAsync(stop.Token) != null) { /* Never mirror private diagnostics. */ }
        });
    }
    public async Task<string?> Read(CancellationToken token) => await process.Output.ReadLineAsync(token);
    public async Task Write(string message, CancellationToken token) => await process.Input.WriteLineAsync(message.AsMemory(), token);
    public async ValueTask DisposeAsync()
    {
        stop.Cancel(); process.Dispose();
        try { await drain; } catch (OperationCanceledException) { }
        stop.Dispose();
    }
}

// Caller transfers ownership of an already-connected diagnostic socket. This
// class never discovers/connects/enrolls/reconnects a server or owns its process.
// reportedPid is observation metadata only, never authorization evidence.
public sealed class WebSocketNativeChannel(WebSocket socket, uint reportedPid) : INativeChannel
{
    public const int MaximumFrameBytes = 2_097_152;
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private readonly SemaphoreSlim writes = new(1, 1);
    public uint Pid => reportedPid;
    public async Task<string?> Read(CancellationToken stop)
    {
        using var data = new MemoryStream(); var buffer = new byte[8192];
        WebSocketReceiveResult frame;
        do
        {
            try { frame = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), stop); }
            catch (WebSocketException) { throw new IOException("Native WebSocket disconnected; no replay"); }
            if (frame.MessageType == WebSocketMessageType.Close) return null;
            if (frame.MessageType != WebSocketMessageType.Text || data.Length + frame.Count > MaximumFrameBytes)
                throw new InvalidDataException("Invalid or oversized native WebSocket frame");
            data.Write(buffer, 0, frame.Count);
        } while (!frame.EndOfMessage);
        try { return Utf8.GetString(data.GetBuffer(), 0, checked((int)data.Length)); }
        catch (DecoderFallbackException) { throw new InvalidDataException("Invalid native WebSocket UTF-8"); }
    }
    public async Task Write(string message, CancellationToken stop)
    {
        byte[] bytes;
        try { bytes = Utf8.GetBytes(message); }
        catch (EncoderFallbackException) { throw new InvalidDataException("Invalid native request UTF-8"); }
        if (bytes.Length > MaximumFrameBytes) throw new InvalidDataException("Native WebSocket request too large");
        await writes.WaitAsync(stop);
        try { await socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, stop); }
        catch (WebSocketException) { throw new IOException("Native WebSocket write failed; no replay"); }
        finally { writes.Release(); }
    }
    public ValueTask DisposeAsync() { socket.Abort(); socket.Dispose(); return ValueTask.CompletedTask; }
}
