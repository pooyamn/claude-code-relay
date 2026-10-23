using System.Text.Json;
using System.Net;

namespace KhadangRouter;

// Availability is a safety property too. Known conversations must not share
// admission fences merely because they share a process or Telegram bot.
internal static class ReliabilityTests
{
    internal static async Task<int> Transports(string root)
    {
        int checks = 0;
        void Check(bool ok, string name) { if (!ok) throw new Exception(name); checks++; }
        using (var ledger = new Ledger(Path.Combine(root, "reliability-http-lanes.db")))
        {
            var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            using var telegram = new Telegram("inert-fixture", ledger, new Handler((_, _) => Task.FromResult(Response(false))),
                new Handler(async (_, stop) => { started.TrySetResult(); await release.Task.WaitAsync(stop); return Response(true); }));
            var upload = telegram.Upload(-100123, 42, "fixture.zip", [80, 75, 3, 4], false, CancellationToken.None);
            try
            {
                await started.Task.WaitAsync(TimeSpan.FromSeconds(2));
                var text = await telegram.Send(-100123, 42, "Text must not wait for a file", CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(2));
                Check(text.GetProperty("message_id").GetInt32() == 10 && !upload.IsCompleted, "Even the SAME topic can send text while upload HTTP is stalled");
            }
            finally { release.TrySetResult(); }
            Check((await upload).GetProperty("message_id").GetInt32() == 20, "Independent upload still records its exact ACK once");
            Check(ledger.Query("SELECT status FROM operations WHERE kind='telegram/sendDocument'").Single()[0] == "confirmed", "Separate lanes preserve the durable upload receipt");
        }
        using (var ledger = new Ledger(Path.Combine(root, "reliability-body-deadline.db")))
        {
            var calls = 0;
            using var telegram = new Telegram("inert-fixture", ledger, new Handler((_, _) => Task.FromResult(Response(false))),
                new Handler((_, _) => { calls++; return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(new StalledBody()) }); }))
            { UploadDeadline = TimeSpan.FromMilliseconds(60) };
            try { await telegram.Upload(-100123, 42, "fixture.zip", [80, 75, 3, 4], false, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(2)); throw new Exception("Stalled body escaped deadline"); }
            catch (TelegramFailure failure) { Check(failure.Code == 0 && !failure.Message.Contains("inert-fixture"), "Upload deadline covers a stalled BODY and does not expose credential URLs"); }
            Check(calls == 1 && ledger.Query("SELECT status FROM operations WHERE kind='telegram/sendDocument'").Single()[0] == "unknown", "Ambiguous body timeout stays unknown with exactly one HTTP attempt");
            Check(ledger.InputUnknown(new(-100123, 42, "Fixture", "/work/a", "fixture")) == 0, "A stalled response body cannot disable native input");
        }
        return checks;
    }
    private static HttpResponseMessage Response(bool file) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(JsonSerializer.Serialize(new
        {
            ok = true,
            result = new { message_id = file ? 20 : 10, chat = new { id = -100123 }, message_thread_id = 42, document = new { file_id = "fixture" } }
        }))
    };
    private sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken stop) => send(request, stop); }
    private sealed class StalledBody : Stream
    {
        public override bool CanRead => true; public override bool CanSeek => false; public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException(); public override long Position { get => 0; set => throw new NotSupportedException(); }
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken stop = default) { await Task.Delay(Timeout.Infinite, stop); return 0; }
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException(); public override void Flush() { }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException(); public override void SetLength(long value) => throw new NotSupportedException();
    }
    internal static int Run(string root)
    {
        var checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        var a = new Binding(-100123, 42, "A", "/work/a", "11111111-1111-4111-8111-111111111111", "codex", "linux");
        var b = new Binding(-100123, 43, "B", "/work/b", "22222222-2222-4222-8222-222222222222", "claude", "linux");
        using (var ledger = new Ledger(Path.Combine(root, "reliability-native.db")))
        {
            ledger.Bind(a); ledger.Bind(b);
            var id = ledger.Attempt("native/turn/start", new { parameters = new { threadId = a.ThreadId, input = new[] { new { type = "text", text = "once" } } } });
            ledger.Outcome(id, "unknown");
            Check(ledger.InputUnknown(a) == 1, "An uncertain model input still fences its exact session");
            Check(ledger.InputUnknown(b) == 0, "An uncertain model input cannot fence an unrelated Claude topic");
            Check(ledger.Unknown == 1 && ledger.Query("SELECT status FROM operations WHERE id=?", id)[0][0] == "unknown", "Scoping does not confirm, discard or replay an uncertain action");
            var bad = ledger.Attempt("native/turn/start", new { parameters = new { threadId = "unregistered" } }); ledger.Outcome(bad, "unknown");
            Check(ledger.InputUnknown(b) == 1, "Unregistered native identity still fails closed globally");
        }
        var path = Path.Combine(root, "reliability-intake.db");
        using (var ledger = new Ledger(path))
        {
            ledger.Bind(a); ledger.Bind(b);
            ledger.Receive(10, JsonSerializer.Serialize(new
            {
                message = new
                {
                    chat = new { id = a.Chat },
                    message_thread_id = a.Topic,
                    from = new { id = 456, is_bot = false },
                    message_id = 99,
                    text = "ordinary instruction"
                }
            }));
            ledger.Claim(10);
        }
        using (var ledger = new Ledger(path))
        {
            Check(ledger.InputUnknown(a) == 1 && ledger.InputUnknown(b) == 0, "Legacy interrupted intake fences only its exact protected topic");
            Check(ledger.Pending().Count == 0 && !ledger.Claim(10), "Scoped interrupted intake is never put back in the dispatch queue");
        }
        using (var ledger = new Ledger(Path.Combine(root, "reliability-output.db")))
        {
            ledger.Bind(a); ledger.Bind(b);
            var id = ledger.Attempt("telegram/sendDocument", new { chat_id = a.Chat, message_thread_id = a.Topic, filename = "video.mp4" });
            ledger.Outcome(id, "unknown");
            Check(ledger.InputUnknown(a) == 0 && ledger.InputUnknown(b) == 0, "An uncertain upload is an output issue, never a native-input fence");
            Check(ledger.Unknown == 1, "Output uncertainty remains in the durable audit");
        }
        foreach (var phase in new[] { "before-intent", "after-intent", "after-ack", "malformed-ack" })
        {
            var crash = Path.Combine(root, "reliability-crash-" + phase + ".db"); string? operation = null;
            using (var ledger = new Ledger(crash))
            {
                ledger.Bind(a); ledger.Bind(b);
                ledger.Receive(20, JsonSerializer.Serialize(new { message = new { chat = new { id = a.Chat }, message_thread_id = a.Topic, text = "once" } })); ledger.Claim(20);
                using (ledger.TrackInput(20, a))
                    if (phase != "before-intent")
                    {
                        operation = ledger.Attempt("native/turn/start", new { parameters = new { threadId = a.ThreadId, input = "once" } });
                        if (phase == "after-ack") ledger.Confirm(operation, JsonSerializer.SerializeToElement(new { turn = new { id = "confirmed-turn" } }));
                        if (phase == "malformed-ack") ledger.Confirm(operation, JsonSerializer.SerializeToElement(new { unexpected = true }));
                    }
            }
            using (var ledger = new Ledger(crash))
            {
                var expected = phase == "before-intent" ? "retained-unsubmitted" : phase == "after-ack" ? "accepted-late" : "unknown";
                Check(ledger.Query("SELECT status FROM updates WHERE id=20")[0][0] == expected, "Restart derives intake disposition from atomic native intent/ACK: " + phase);
                Check(ledger.InputUnknown(b) == 0, "Every crash point preserves unrelated-topic admission: " + phase);
                Check(ledger.Pending().Count == 0 && !ledger.Claim(20), "Crash recovery never replays input: " + phase);
                if (phase == "after-intent") Check(ledger.InputUnknown(a) > 0 && ledger.Query("SELECT status FROM operations WHERE id=?", operation)[0][0] == "unknown", "Possible native mutation remains fenced and unknown");
            }
        }
        var contention = Path.Combine(root, "reliability-contention.db");
        var latePath = Path.Combine(root, "reliability-late-claude.db"); string lateOperation;
        const string uuid = "33333333-3333-4333-8333-333333333333";
        using (var ledger = new Ledger(latePath))
        {
            ledger.Bind(b);
            ledger.Receive(30, JsonSerializer.Serialize(new { message = new { chat = new { id = b.Chat }, message_thread_id = b.Topic, text = "once" } })); ledger.Claim(30);
            using (ledger.TrackInput(30, b)) lateOperation = ledger.Attempt("claude/user/send-now", new { SessionId = b.ThreadId, uuid, content = "once" });
        }
        using (var ledger = new Ledger(latePath))
        {
            JsonElement Echo(string text) => JsonSerializer.SerializeToElement(new { type = "user", session_id = b.ThreadId, uuid,
                parent_tool_use_id = (object?)null, message = new { role = "user", content = text } });
            try { ClaudeDelivery.ConfirmReplay(ledger, b.ThreadId, Echo("changed")); throw new Exception("Foreign echo accepted"); }
            catch (InvalidDataException) { Check(ledger.InputUnknown(b) > 0, "Content-mismatched late echo cannot resolve uncertain input"); }
            Check(ClaudeDelivery.ConfirmReplay(ledger, b.ThreadId, Echo("once")) == lateOperation, "Exact late native echo reconciles the original operation after restart");
            Check(ledger.Query("SELECT status FROM updates WHERE id=30")[0][0] == "accepted-late" && ledger.InputUnknown(b) == 0,
                "Late ACK clears the interrupted intake fence without another restart or resend");
            Check(ledger.Pending().Count == 0 && !ledger.Claim(30), "Late receipt reconciliation never queues the acknowledged input");
        }
        using (var one = new Ledger(contention))
        using (var two = new Ledger(contention))
        using (var acquired = new ManualResetEventSlim())
        using (var release = new ManualResetEventSlim())
        {
            var holder = Task.Run(() => one.Transaction(() => { acquired.Set(); if (!release.Wait(3000)) throw new Exception("Contention fixture timed out"); }));
            Check(acquired.Wait(2000), "Contention fixture acquired a bounded writer");
            var writer = Task.Run(() => two.Put("bounded-contention", new { retained = true }));
            Thread.Sleep(80); release.Set(); Task.WaitAll(holder, writer);
            Check(two.Get("bounded-contention") != null, "Brief protected-writer contention does not kill native event observers");
        }
        return checks;
    }
}
