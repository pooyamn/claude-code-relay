using System.Net.WebSockets;
using System.Text;

namespace KhadangRouter;

// Framing only, NOT peer/role authentication or a deployment grant. The native
// launcher owns stdio. LinuxCodexChannel additionally verifies the limited owner
// and the pinned connector's actual Unix-peer observations. A reported PID or
// connected socket alone is never that boundary.
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
    private readonly NativeJsonlReader frames;
    public uint Pid => process.Pid;
    public StdioNativeChannel(WindowsOwnerProcess process)
    {
        this.process = process;
        frames = new NativeJsonlReader(process.Output);
        drain = Task.Run(async () => {
            while (await process.Error.ReadLineAsync(stop.Token) != null) { /* Never mirror private diagnostics. */ }
        });
    }
    public Task<string?> Read(CancellationToken token) => frames.Read(token);
    public async Task Write(string message, CancellationToken token)
    {
        NativeJsonlReader.ValidateWrite(message);
        await process.Input.WriteLineAsync(message.AsMemory(), token);
    }
    public async ValueTask DisposeAsync()
    {
        stop.Cancel(); process.Dispose();
        try { await drain; } catch (Exception error) when (error is OperationCanceledException or IOException or ObjectDisposedException) { }
        stop.Dispose();
    }
}

// Read complete bounded JSONL frames before RPC sees them. ReadLineAsync alone
// can allocate an unbounded line, and it accepts a partial line at EOF. Neither
// is safe for the connector's uncertain-delivery boundary.
internal sealed class NativeJsonlReader(TextReader source, int maximumBytes = WebSocketNativeChannel.MaximumFrameBytes)
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private readonly char[] buffer = new char[8192];
    private int cursor, filled;
    public async Task<string?> Read(CancellationToken stop)
    {
        var line = new StringBuilder();
        while (true)
        {
            stop.ThrowIfCancellationRequested();
            if (cursor == filled)
            {
                filled = await source.ReadAsync(buffer.AsMemory(), stop); cursor = 0;
                if (filled == 0)
                {
                    if (line.Length != 0) throw new InvalidDataException("Incomplete native frame at EOF; no replay");
                    return null;
                }
            }
            var end = Array.IndexOf(buffer, '\n', cursor, filled - cursor);
            var count = (end < 0 ? filled : end) - cursor;
            if (line.Length + count > maximumBytes + 1L) throw new InvalidDataException("Native JSONL frame exceeds bound");
            line.Append(buffer, cursor, count); cursor += count;
            if (end < 0) continue;
            cursor++;
            if (line.Length > 0 && line[^1] == '\r') line.Length--;
            var message = line.ToString();
            ValidateWrite(message, maximumBytes); return message;
        }
    }
    internal static void ValidateWrite(string message, int maximumBytes = WebSocketNativeChannel.MaximumFrameBytes)
    {
        try
        {
            if (message.IndexOfAny(['\r', '\n']) >= 0 || Utf8.GetByteCount(message) > maximumBytes)
                throw new InvalidDataException("Invalid or oversized single native JSONL frame");
        }
        catch (EncoderFallbackException) { throw new InvalidDataException("Invalid native frame Unicode"); }
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
