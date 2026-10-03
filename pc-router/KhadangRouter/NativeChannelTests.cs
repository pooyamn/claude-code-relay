using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;

namespace KhadangRouter;

public static class NativeChannelTests
{
    public static async Task<int> Run(string root)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        var json = "{\"text\":\"🙂\"}"; var bytes = Encoding.UTF8.GetBytes(json);
        using (var socket = new FakeSocket())
        {
            socket.Frames.Enqueue((bytes[..12], WebSocketMessageType.Text, false));
            socket.Frames.Enqueue((bytes[12..], WebSocketMessageType.Text, true));
            await using var wire = new WebSocketNativeChannel(socket, 123);
            Check(await wire.Read(stop.Token) == json && wire.Pid == 123, "Fragmented Unicode frame survives without PID authority");
            await wire.Write(json, stop.Token);
            Check(Encoding.UTF8.GetString(socket.Sent.Single()) == json, "One native JSON message is one text frame");
        }
        foreach (var mode in new[] { "binary", "utf8", "oversized", "close" })
        {
            using var socket = new FakeSocket();
            if (mode == "oversized") for (int i = 0; i <= WebSocketNativeChannel.MaximumFrameBytes / 8192; i++) socket.Frames.Enqueue((new byte[8192], WebSocketMessageType.Text, false));
            else socket.Frames.Enqueue((mode == "utf8" ? [255] : [], mode == "binary" ? WebSocketMessageType.Binary : mode == "close" ? WebSocketMessageType.Close : WebSocketMessageType.Text, true));
            await using var wire = new WebSocketNativeChannel(socket, 123);
            try { var read = await wire.Read(stop.Token); Check(mode == "close" && read == null, "Close frame is terminal, not reconnect"); }
            catch (InvalidDataException) { Check(mode != "close", "Bad native frames fail closed"); }
        }
        using (var socket = new FakeSocket())
        {
            await using var wire = new WebSocketNativeChannel(socket, 123);
            try { await wire.Write(new string('x', WebSocketNativeChannel.MaximumFrameBytes + 1), stop.Token); throw new Exception("Large request sent"); }
            catch (InvalidDataException) { Check(socket.Sent.Count == 0, "Oversized native request is not sent"); }
        }
        foreach (var mode in new[] { "normal", "reject", "disconnect" })
        {
            var path = Path.Combine(root, "channel-" + mode); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "rpc.db"));
            var channel = new FakeChannel(mode);
            await using var rpc = new NativeRpc(channel, ledger);
            int notifications = 0;
            rpc.Notification += m => { if (m.GetProperty("method").GetString() == "test/event") notifications++; };
            try
            {
                await rpc.Call("test/mutation", new { }, stop.Token);
                Check(mode == "normal" && ledger.Unknown == 0 && notifications == 1, "Transport-independent RPC keeps event and confirmed effect");
            }
            catch (NativeRejected) { Check(mode == "reject" && ledger.Unknown == 0, "Explicit native rejection is not overwritten as unknown"); }
            catch (IOException) { Check(mode == "disconnect" && ledger.Unknown == 1, "Disconnected mutation remains unknown"); }
            Check(channel.Writes.Count == 1, "No native mutation replay or reconnect");
            if (mode == "disconnect")
            {
                try { await rpc.Call("test/read", new { }, stop.Token, effect: false); throw new Exception("Disconnected channel reused"); }
                catch (IOException) { Check(channel.Writes.Count == 1, "Disconnected stream rejects later submission before writing"); }
            }
        }
        return checks;
    }
    private sealed class FakeChannel(string mode) : INativeChannel
    {
        private readonly Channel<string?> frames = Channel.CreateUnbounded<string?>();
        public uint Pid => 123;
        public List<string> Writes = [];
        public async Task<string?> Read(CancellationToken stop) => await frames.Reader.ReadAsync(stop);
        public Task Write(string message, CancellationToken stop)
        {
            Writes.Add(message); using var doc = JsonDocument.Parse(message); var id = doc.RootElement.GetProperty("id").GetInt64();
            frames.Writer.TryWrite(mode == "disconnect" ? null : JsonSerializer.Serialize(new { method = "test/event", @params = new { } }));
            if (mode != "disconnect") frames.Writer.TryWrite(mode == "reject" ? JsonSerializer.Serialize(new { id, error = new { code = 123 } }) : JsonSerializer.Serialize(new { id, result = new { ok = true } }));
            return Task.CompletedTask;
        }
        public ValueTask DisposeAsync() { frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }
    private sealed class FakeSocket : WebSocket
    {
        public Queue<(byte[] Bytes, WebSocketMessageType Type, bool End)> Frames = [];
        public List<byte[]> Sent = [];
        public override WebSocketCloseStatus? CloseStatus => null;
        public override string? CloseStatusDescription => null;
        public override WebSocketState State => WebSocketState.Open;
        public override string? SubProtocol => null;
        public override void Abort() { }
        public override void Dispose() { }
        public override Task CloseAsync(WebSocketCloseStatus status, string? description, CancellationToken stop) => Task.CompletedTask;
        public override Task CloseOutputAsync(WebSocketCloseStatus status, string? description, CancellationToken stop) => Task.CompletedTask;
        public override Task<WebSocketReceiveResult> ReceiveAsync(ArraySegment<byte> target, CancellationToken stop)
        {
            var frame = Frames.Dequeue(); frame.Bytes.CopyTo(target.Array!, target.Offset);
            return Task.FromResult(new WebSocketReceiveResult(frame.Bytes.Length, frame.Type, frame.End));
        }
        public override Task SendAsync(ArraySegment<byte> bytes, WebSocketMessageType type, bool end, CancellationToken stop)
        { if (type != WebSocketMessageType.Text || !end) throw new Exception("Wrong native frame"); Sent.Add(bytes.ToArray()); return Task.CompletedTask; }
    }
}
