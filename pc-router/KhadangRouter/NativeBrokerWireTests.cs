using System.Buffers.Binary;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;

namespace KhadangRouter;

// Inert streams/native only. These do not establish Windows peer identity,
// production admission, real approval handling or phone continuity.
public static class NativeBrokerWireTests
{
    public static async Task<int> Run(string root)
    {
        var checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        string Intent() => Guid.NewGuid().ToString("N");
        async Task Refused<T>(Task<T> work, Type expected, string name)
        {
            try { await work.WaitAsync(TimeSpan.FromSeconds(10)); throw new Exception(name + " accepted"); }
            catch (Exception error) when (expected.IsInstanceOfType(error)) { checks++; }
        }
        var fake = new Fake();
        await using (var broker = NativeBroker.Fixture(fake, fake, new Ledger(Path.Combine(root, "broker-wire.db")), fake.Initialize))
        {
            await broker.Ready;
            var first = new Connection(broker);
            var status = await first.Client.Status(CancellationToken.None);
            Check(status.Epoch == broker.Epoch && status.Pid == fake.Pid && status.Position == 0, "Wire status binds native epoch/PID and custody cursor");
            using var canceled = new CancellationTokenSource();
            var intent = Intent();
            var wait = first.Client.Call(intent, "test/slow", new { input = "one" }, canceled.Token);
            await fake.Started.Task.WaitAsync(TimeSpan.FromSeconds(10));
            Check((await first.Client.Status(CancellationToken.None)).Pid == fake.Pid, "Pending native call does not block wire status");
            canceled.Cancel();
            await Refused(wait, typeof(OperationCanceledException), "Canceled wire waiter");
            await first.DisposeAsync();
            Check(fake.Calls == 1 && !fake.Disposed && fake.Initializations == 1, "Client EOF/detach does not cancel/dispose/reinitialize native custody");
            fake.Raw("{ \"method\" : \"item/agentMessage/delta\", \"params\": {\"threadId\":\"thread\",\"delta\":\"\\u0061\\\"\\n🙂\"} }");
            await using var second = new Connection(broker);
            var joined = second.Client.Call(intent, "test/slow", new { input = "one" }, CancellationToken.None);
            fake.Release.TrySetResult(JsonSerializer.SerializeToElement(new { ok = true }));
            Check((await joined).GetProperty("ok").GetBoolean() && fake.Calls == 1, "Replacement wire client joins original stable intent without resubmission");
            var events = await second.Client.Events(0, 100, CancellationToken.None);
            Check(events.Count == 1 && events[0].Frame.GetRawText() == fake.LastRaw && events[0].Position == 1, "Offline event preserves exact raw JSON/Unicode/escaping through wire");
            Check((await second.Client.Events(0, 100, CancellationToken.None)).Count == 1, "Wire event read does not acknowledge/drop custody");
            await Refused(second.Client.Call(intent, "test/slow", new { input = "changed" }, CancellationToken.None), typeof(InvalidDataException), "Changed stable wire intent");
            foreach (var method in new[] { "initialize", "initialized" })
                await Refused(second.Client.Call(Intent(), method, new { }, CancellationToken.None), typeof(InvalidDataException), "Client initialization");
            Check(fake.Initializations == 1 && fake.Calls == 1, "Wire clients cannot initialize native transport");
            fake.Raw("{ \"id\" : 42, \"method\":\"item/commandExecution/requestApproval\", \"params\":{\"threadId\":\"thread\",\"turnId\":\"turn\",\"raw\":\"\\u0061\\\"\\n\"} }");
            var request = (await second.Client.Requests(null, 100, CancellationToken.None)).Single();
            Check(request.Frame.GetRawText() == fake.LastRaw && request.Id.GetInt32() == 42, "Reviewed request retains complete fingerprinted native frame");
            await Refused(second.Client.Reply(request with { Thread = "other" }, new { decision = "decline" }, CancellationToken.None), typeof(InvalidDataException), "Forged wire review scope");
            var written = await second.Client.Reply(request, new { decision = "decline" }, CancellationToken.None);
            Check(written.GetProperty("written").GetBoolean() && !written.GetProperty("accepted").GetBoolean() && fake.Replies == 1, "Reply receipt means observed write, never acceptance");
            await Refused(second.Client.Reply(request, new { decision = "decline" }, CancellationToken.None), typeof(InvalidDataException), "Consumed wire review");
            fake.Raw("{\"id\":\"connection\",\"method\":\"account/chatgptAuthTokens/refresh\",\"params\":{}}");
            Check((await second.Client.Requests(null, 100, CancellationToken.None)).Count == 0, "Thread wire inbox cannot expose connection request as thread approval");
            var before = broker.Position;
            for (var i = 0; i < 5; i++) fake.Raw(JsonSerializer.Serialize(new { method = "test/large", @params = new { data = new string('x', 1_300_000) } }));
            var page = await second.Client.Events(before, 100, CancellationToken.None);
            Check(page.Count is > 0 and < 5 && page.All(e => e.Frame.GetProperty("params").GetProperty("data").GetString()!.Length == 1_300_000), "Wire byte bound paginates complete native frames, never truncates them");
            Check(page.Count + (await second.Client.Events(page.Last().Position, 100, CancellationToken.None)).Count == 5, "Returned custody cursor recovers remaining oversized page items");
            var rejected = Intent(); var failed = Intent();
            for (var i = 0; i < 2; i++) await Refused(second.Client.Call(rejected, "test/reject", new { }, CancellationToken.None), typeof(NativeRejected), "Rejected native wire intent");
            for (var i = 0; i < 2; i++) await Refused(second.Client.Call(failed, "test/disconnect", new { }, CancellationToken.None), typeof(IOException), "Unknown native wire intent");
            Check(fake.Calls == 3 && broker.Unknown == 1, "Rejected/ambiguous wire calls retain stable outcomes without native replay");
            await Refused(second.Client.Call(Intent(), "thread/goal/set", new { }, CancellationToken.None), typeof(IOException), "Unknown outcome mutation fence");
            await second.Client.Call(Intent(), "thread/goal/get", new { }, CancellationToken.None);
            Check(fake.Calls == 4, "Read-only reconciliation remains usable behind unknown fence");
        }
        Check(fake.Disposed, "Only native broker shutdown disposes native ownership");
        var shaped = new Fake();
        await using (var broker = NativeBroker.Fixture(shaped, shaped, new Ledger(Path.Combine(root, "broker-wire-shapes.db")), shaped.Initialize))
        {
            await broker.Ready;
            foreach (var bad in new[] {
                new BrokerWireRequest(1, Intent(), "status", broker.Epoch, Method: "account/read"),
                new BrokerWireRequest(1, Intent(), "call", broker.Epoch, Intent: Intent(), Method: "account/read"),
                new BrokerWireRequest(1, Intent(), "events", broker.Epoch, Cursor: 0, Maximum: 101),
                new BrokerWireRequest(1, Intent(), "requests", broker.Epoch, Cursor: 0, Maximum: 1),
                new BrokerWireRequest(1, Intent(), "reply", broker.Epoch, Result: JsonSerializer.SerializeToElement(new { })),
                new BrokerWireRequest(1, Intent(), "start-another-native", broker.Epoch) })
            {
                var pair = Duplex.Pair(); using var local = pair.Left; using var remote = pair.Right;
                using var attached = broker.AttachFixture(() => { }); using var writes = new SemaphoreSlim(1, 1);
                var server = NativeBrokerWire.ServeAttached(attached, remote, _ => { }, CancellationToken.None);
                await BrokerWireFrames.Write(local, bad, writes, CancellationToken.None);
                var response = (await BrokerWireFrames.Read(local, CancellationToken.None))!.Value;
                Check(response.GetProperty("Status").GetString() == "refused" && shaped.Calls == 0, "Exact wire operation shape before effect: " + bad.Kind);
                local.Dispose(); await server.WaitAsync(TimeSpan.FromSeconds(10));
            }
            foreach (var bad in new[] {
                new BrokerWireRequest(2, Intent(), "status", broker.Epoch),
                new BrokerWireRequest(1, "self-chosen-id", "status", broker.Epoch),
                new BrokerWireRequest(1, Intent(), "status", Intent()) })
            {
                var pair = Duplex.Pair(); using var local = pair.Left; using var remote = pair.Right;
                using var attached = broker.AttachFixture(() => { }); using var writes = new SemaphoreSlim(1, 1);
                var server = NativeBrokerWire.ServeAttached(attached, remote, _ => { }, CancellationToken.None);
                await BrokerWireFrames.Write(local, bad, writes, CancellationToken.None);
                await Refused(server.ContinueWith(t => { t.GetAwaiter().GetResult(); return true; }), typeof(InvalidDataException), "Stale/unknown wire envelope identity");
                Check(shaped.Calls == 0, "Invalid wire identity cannot reach native effect");
            }
        }
        // Caller cancellation with an attached client keeps correlation until a
        // late response arrives; it must not poison later controls.
        var late = new Fake();
        await using (var broker = NativeBroker.Fixture(late, late, new Ledger(Path.Combine(root, "broker-wire-late.db")), late.Initialize))
        {
            await using var attached = new Connection(broker); using var cancel = new CancellationTokenSource();
            var id = Intent(); var wait = attached.Client.Call(id, "test/slow", new { }, cancel.Token);
            await late.Started.Task.WaitAsync(TimeSpan.FromSeconds(10)); cancel.Cancel();
            await Refused(wait, typeof(OperationCanceledException), "Late wire waiter");
            late.Release.TrySetResult(JsonSerializer.SerializeToElement(new { ok = true }));
            await attached.Client.Call(id, "test/slow", new { }, CancellationToken.None);
            Check((await attached.Client.Status(CancellationToken.None)).Pid == late.Pid && late.Calls == 1, "Late canceled-call response remains correlated, no replacement native action");
        }
        // Mandatory policy can refuse even reads before any native effect.
        var denied = new Fake();
        await using (var broker = NativeBroker.Fixture(denied, denied, new Ledger(Path.Combine(root, "broker-wire-denied.db")), denied.Initialize))
        {
            await using var attached = new Connection(broker, _ => throw new UnauthorizedAccessException("Inert fixture policy denial"));
            await Refused(attached.Client.Call(Intent(), "account/read", new { }, CancellationToken.None), typeof(InvalidDataException), "Wire policy denial");
            Check(denied.Calls == 0, "Caller policy executes before any native call");
        }
        var nullable = new Fake();
        await using (var broker = NativeBroker.Fixture(nullable, nullable, new Ledger(Path.Combine(root, "broker-wire-null.db")), nullable.Initialize))
        {
            await using var attached = new Connection(broker);
            Check((await attached.Client.Call(Intent(), "test/null", new { }, CancellationToken.None)).ValueKind == JsonValueKind.Null,
                "Explicit null native result is distinct from a missing response payload");
            nullable.Raw("{\"id\":\"null-result\",\"method\":\"item/commandExecution/requestApproval\",\"params\":{\"threadId\":\"thread\"}}");
            var request = (await attached.Client.Requests(null, 100, CancellationToken.None)).Single();
            var written = await attached.Client.Reply(request, JsonSerializer.SerializeToElement<object?>(null), CancellationToken.None);
            Check(written.GetProperty("written").GetBoolean() && nullable.LastReplyNull,
                "Explicit null reply result reaches native unchanged; missing result remains refused");
        }
        // Malformed envelopes must fail every outstanding waiter, including the
        // one named by the response; removing it too early caused a real hang.
        foreach (var variant in new[] { "epoch", "missing-data", "unknown-status", "unknown-id", "extra-field" })
        {
            var pair = Duplex.Pair(); var epoch = Intent();
            await using var client = NativeBrokerWireClient.Fixture(pair.Left, epoch); using var remote = pair.Right;
            var wait = client.Status(CancellationToken.None);
            var request = (await BrokerWireFrames.Read(remote, CancellationToken.None))!.Value;
            var response = new Dictionary<string, object?> { ["Protocol"] = 1, ["Id"] = request.GetProperty("Id").GetString(), ["Epoch"] = epoch,
                ["Status"] = "confirmed", ["Data"] = new BrokerWireStatus(epoch, 1, 0) };
            if (variant == "epoch") response["Epoch"] = Intent();
            if (variant == "missing-data") response.Remove("Data");
            if (variant == "unknown-status") response["Status"] = "accepted-maybe";
            if (variant == "unknown-id") response["Id"] = Intent();
            if (variant == "extra-field") response["fallback"] = true;
            using var writes = new SemaphoreSlim(1, 1); await BrokerWireFrames.Write(remote, response, writes, CancellationToken.None);
            await Refused(wait, typeof(IOException), "Malformed broker reply " + variant);
            await Refused(client.Status(CancellationToken.None), typeof(IOException), "Malformed transport must not reconnect");
        }
        // Bound admission atomically under actual concurrent callers, retaining
        // canceled-but-submitted correlations until response or disconnection.
        {
            var pair = Duplex.Pair(); await using var client = NativeBrokerWireClient.Fixture(pair.Left, Intent()); using var remote = pair.Right;
            var calls = Enumerable.Range(0, 64).Select(_ => Task.Run(async () => {
                try { await client.Status(CancellationToken.None); return "confirmed"; }
                catch (InvalidOperationException) { return "bound"; } catch (IOException) { return "closed"; }
            })).ToArray();
            for (var i = 0; i < 32; i++) await BrokerWireFrames.Read(remote, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10));
            // All 32 excess callers must hit the bound before closing the stream.
            using var excess = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            while (calls.Count(c => c.IsCompletedSuccessfully) < 32) await Task.Delay(1, excess.Token);
            await client.DisposeAsync();
            var outcomes = await Task.WhenAll(calls);
            Check(outcomes.Count(o => o == "bound") == 32 && outcomes.Count(o => o == "closed") == 32, "Concurrent wire admission never exceeds 32 outstanding and disposal settles every waiter");
        }
        foreach (var raw in new[] { "[]", "{\"Protocol\":1,\"Protocol\":2}", "{broken" })
        {
            using var stream = new MemoryStream(Packet(raw));
            try { await BrokerWireFrames.Read(stream, CancellationToken.None); throw new Exception("Malformed wire frame accepted"); }
            catch (Exception error) when (error is InvalidDataException or JsonException) { checks++; }
        }
        foreach (var size in new[] { -1, 0, 1, BrokerWireFrames.MaximumBytes + 1 })
        {
            var header = new byte[4]; BinaryPrimitives.WriteInt32BigEndian(header, size); using var stream = new MemoryStream(header);
            await Refused(BrokerWireFrames.Read(stream, CancellationToken.None), typeof(InvalidDataException), "Bounded wire length");
        }
        using (var shortFrame = new MemoryStream(Packet("{}")[..^1]))
            await Refused(BrokerWireFrames.Read(shortFrame, CancellationToken.None), typeof(EndOfStreamException), "Truncated wire body");
        {
            var pair = Duplex.Pair(); using var left = pair.Left; using var right = pair.Right; using var writes = new SemaphoreSlim(1, 1);
            left.FragmentReads = true;
            await BrokerWireFrames.Write(right, new { text = "سلام 🙂" }, writes, CancellationToken.None);
            Check((await BrokerWireFrames.Read(left, CancellationToken.None))!.Value.GetProperty("text").GetString() == "سلام 🙂", "Fragmented UTF-8 frame remains complete");
            await writes.WaitAsync(); using var cancel = new CancellationTokenSource();
            var queued = BrokerWireFrames.Write(right, new { text = "must-not-submit" }, writes, CancellationToken.None, cancel.Token);
            cancel.Cancel(); await Refused(queued.ContinueWith(t => { t.GetAwaiter().GetResult(); return true; }), typeof(OperationCanceledException), "Canceled pre-write admission");
            writes.Release(); right.Dispose();
            Check(await BrokerWireFrames.Read(left, CancellationToken.None) == null, "Cancellation before write emits no header or body");
        }
        // A failed client write must close only its connection and settle other
        // outstanding waits rather than leaving the reader hung forever.
        {
            var pair = Duplex.Pair(); var faulty = new FaultStream(pair.Left);
            await using var client = NativeBrokerWireClient.Fixture(faulty, Intent()); using var remote = pair.Right;
            var first = client.Status(CancellationToken.None); await BrokerWireFrames.Read(remote, CancellationToken.None);
            faulty.FailWrites = true;
            await Refused(client.Status(CancellationToken.None), typeof(IOException), "Failed wire write");
            await Refused(first, typeof(IOException), "Other waiter on failed wire write");
        }
        return checks;
    }
    private static byte[] Packet(string json)
    { var body = Encoding.UTF8.GetBytes(json); var result = new byte[4 + body.Length]; BinaryPrimitives.WriteInt32BigEndian(result, body.Length); body.CopyTo(result, 4); return result; }
    internal sealed class Connection : IAsyncDisposable
    {
        private readonly NativeBrokerSession attached;
        private readonly Duplex remote;
        private readonly Task server;
        public NativeBrokerWireClient Client { get; }
        public Connection(NativeBroker broker, Action<BrokerWireRequest>? authorize = null)
        {
            var pair = Duplex.Pair(); remote = pair.Right; attached = broker.AttachFixture(() => { });
            // Allow-all is ONLY the inert fake policy, never a public default.
            server = NativeBrokerWire.ServeAttached(attached, remote, authorize ?? (_ => { }), CancellationToken.None);
            Client = NativeBrokerWireClient.Fixture(pair.Left, broker.Epoch);
        }
        public async ValueTask DisposeAsync()
        {
            await Client.DisposeAsync();
            try { await server.WaitAsync(TimeSpan.FromSeconds(10)); }
            finally { attached.Dispose(); remote.Dispose(); }
        }
    }
    private sealed class Fake : INative, IAsyncDisposable
    {
        public uint Pid => 41;
        public int Calls, Initializations, Replies;
        public bool Disposed;
        public bool LastReplyNull;
        public string? LastRaw;
        public TaskCompletionSource Started = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource<JsonElement> Release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public event Action<JsonElement>? Notification;
        public Task Initialize() { Initializations++; return Task.CompletedTask; }
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken token, bool effect = true)
        {
            Interlocked.Increment(ref Calls); Started.TrySetResult();
            if (method == "test/reject") throw new NativeRejected(method);
            if (method == "test/disconnect") throw new IOException("Inert native unknown outcome");
            if (method == "test/null") return JsonSerializer.SerializeToElement<object?>(null);
            return method == "test/slow" ? await Release.Task.WaitAsync(token) : JsonSerializer.SerializeToElement(new { ok = true });
        }
        public Task Reply(JsonElement id, object result, CancellationToken token)
        { Replies++; LastReplyNull = result is JsonElement value && value.ValueKind == JsonValueKind.Null; return Task.CompletedTask; }
        public void Raw(string frame) { LastRaw = frame; using var parsed = JsonDocument.Parse(frame); Notification?.Invoke(parsed.RootElement.Clone()); }
        public ValueTask DisposeAsync() { Disposed = true; return ValueTask.CompletedTask; }
    }
    private sealed class Duplex : Stream
    {
        private readonly Channel<byte[]> incoming, outgoing;
        private byte[] current = []; private int offset;
        public bool FragmentReads;
        private Duplex(Channel<byte[]> incoming, Channel<byte[]> outgoing) { this.incoming = incoming; this.outgoing = outgoing; }
        public static (Duplex Left, Duplex Right) Pair()
        { var a = Channel.CreateUnbounded<byte[]>(); var b = Channel.CreateUnbounded<byte[]>(); return (new(a, b), new(b, a)); }
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken token = default)
        {
            if (buffer.Length == 0) return 0;
            while (offset == current.Length)
            {
                if (!await incoming.Reader.WaitToReadAsync(token)) return 0;
                if (!incoming.Reader.TryRead(out current!)) continue;
                offset = 0;
            }
            var size = Math.Min(buffer.Length, current.Length - offset); if (FragmentReads) size = Math.Min(size, 1);
            current.AsMemory(offset, size).CopyTo(buffer); offset += size; return size;
        }
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken token = default)
        { token.ThrowIfCancellationRequested(); if (!outgoing.Writer.TryWrite(buffer.ToArray())) throw new IOException("Inert duplex closed"); return ValueTask.CompletedTask; }
        protected override void Dispose(bool disposing) { if (disposing) { incoming.Writer.TryComplete(); outgoing.Writer.TryComplete(); } base.Dispose(disposing); }
        public override bool CanRead => true; public override bool CanWrite => true; public override bool CanSeek => false;
        public override long Length => throw new NotSupportedException(); public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override int Read(byte[] b, int o, int n) => throw new NotSupportedException(); public override void Write(byte[] b, int o, int n) => throw new NotSupportedException();
        public override void Flush() { } public override Task FlushAsync(CancellationToken token) => Task.CompletedTask;
        public override long Seek(long o, SeekOrigin origin) => throw new NotSupportedException(); public override void SetLength(long n) => throw new NotSupportedException();
    }
    private sealed class FaultStream(Stream inner) : Stream
    {
        public bool FailWrites;
        public override ValueTask<int> ReadAsync(Memory<byte> b, CancellationToken t = default) => inner.ReadAsync(b, t);
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> b, CancellationToken t = default) => FailWrites ? throw new IOException("Inert failed wire write") : inner.WriteAsync(b, t);
        protected override void Dispose(bool disposing) { if (disposing) inner.Dispose(); base.Dispose(disposing); }
        public override bool CanRead => true; public override bool CanWrite => true; public override bool CanSeek => false;
        public override long Length => throw new NotSupportedException(); public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override int Read(byte[] b, int o, int n) => throw new NotSupportedException(); public override void Write(byte[] b, int o, int n) => throw new NotSupportedException();
        public override void Flush() { } public override Task FlushAsync(CancellationToken t) => Task.CompletedTask;
        public override long Seek(long o, SeekOrigin s) => throw new NotSupportedException(); public override void SetLength(long n) => throw new NotSupportedException();
    }
}
