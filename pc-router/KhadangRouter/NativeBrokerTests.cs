using System.Text.Json;

namespace KhadangRouter;

public static class NativeBrokerTests
{
    public static async Task<int> Run(string root)
    {
        var checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        string Intent() => Guid.NewGuid().ToString("N");
        foreach (var key in new[] { "PATH", "SystemRoot", "USERPROFILE", "TEMP" })
            Check(WindowsOwnerProcess.AllowedDiagnosticVariable(key), "Diagnostic child retains required OS-runtime variable");
        foreach (var key in new[] { "OPENAI_API_KEY", "CODEX_ACCESS_TOKEN", "GH_TOKEN", "CLOUDFLARE_API_TOKEN", "TELEGRAM_BOT_TOKEN", "VPN_SECRET", "DOTNET_STARTUP_HOOKS", "UNKNOWN_SECRET" })
            Check(!WindowsOwnerProcess.AllowedDiagnosticVariable(key), "Positive diagnostic environment cannot export arbitrary credentials/hooks");
        var path = Path.Combine(root, "broker.db");
        var fake = new Fake();
        var ledger = new Ledger(path);
        await using (var broker = NativeBroker.Fixture(fake, fake, ledger, fake.Initialize))
        {
            await broker.Ready;
            using var first = broker.AttachFixture(() => { });
            using var canceled = new CancellationTokenSource();
            var intent = Intent();
            var wait = first.Call(intent, "test/slow", new { input = "one" }, canceled.Token);
            await fake.Started.Task;
            canceled.Cancel(); first.Dispose();
            try { await wait; throw new Exception("Canceled waiter returned"); } catch (OperationCanceledException) { checks++; }
            fake.Release.SetResult(JsonSerializer.SerializeToElement(new { ok = true }));
            using var second = broker.AttachFixture(() => { });
            var result = await second.Call(intent, "test/slow", new { input = "one" }, CancellationToken.None);
            Check(result.GetProperty("ok").GetBoolean() && fake.Calls == 1 && fake.Initializations == 1 && !fake.Disposed,
                "Client cancellation/detach does not cancel native work, reinitialize, dispose or replay it");
            try { await second.Call(intent, "test/slow", new { input = "changed" }, CancellationToken.None); throw new Exception("Changed intent accepted"); }
            catch (InvalidDataException) { checks++; }
            var cursor = broker.Position;
            fake.Emit("item/agentMessage/delta", new { threadId = "thread", delta = "offline" });
            fake.Emit("turn/completed", new { threadId = "thread", turn = new { id = "turn", status = "completed" } });
            var events = second.Events(cursor);
            Check(events.Count == 2 && events[0].Position == cursor + 1 && events[1].Position == cursor + 2 && events.All(e => e.Epoch == broker.Epoch),
                "Offline native events retain complete ordered current-epoch custody");
            Check(second.Events(cursor).Count == 2, "Reading events does not silently acknowledge/drop them");
            foreach (var invalid in new[] { -1L, broker.Position + 1 })
            {
                try { second.Events(invalid); throw new Exception("Invalid cursor accepted"); } catch (InvalidDataException) { checks++; }
            }
            fake.Request(42, "thread", "turn");
            var request = second.Requests().Single();
            foreach (var bad in new[] { request with { Epoch = Intent() }, request with { Thread = "other" }, request with { Turn = "other" }, request with { Fingerprint = "other" } })
            {
                try { await second.Reply(bad, new { decision = "accept" }); throw new Exception("Stale review accepted"); } catch (InvalidDataException) { checks++; }
            }
            fake.Emit("serverRequest/resolved", new { threadId = "thread", requestId = 42 });
            Check(second.Requests().Count == 0, "Native resolution removes pending approval");
            try { await second.Reply(request, new { decision = "accept" }); throw new Exception("Resolved request replied"); } catch (InvalidDataException) { checks++; }
            Check(fake.Replies == 0, "Resolved/stale approvals fail before native write");
            fake.Request("42", "thread", "turn");
            var stringRequest = second.Requests().Single();
            Check(stringRequest.Id.ValueKind == JsonValueKind.String, "Numeric/string request IDs remain distinct");
            fake.ResolveDuringReply = true;
            await second.Reply(stringRequest, new { decision = "decline" });
            Check(second.Requests().Count == 0 && ledger.Query("SELECT status FROM broker_replies").Single()[0] == "resolved-unattributed",
                "Resolution during write is not overwritten or mislabeled accepted decision");
            try { await second.Reply(stringRequest, new { decision = "decline" }); throw new Exception("Reply replayed"); } catch (InvalidDataException) { checks++; }
            var rejected = Intent();
            for (var i = 0; i < 2; i++)
            {
                try { await second.Call(rejected, "test/reject", new { }, CancellationToken.None); throw new Exception("Rejection accepted"); } catch (NativeRejected) { checks++; }
            }
            Check(broker.Unknown == 0 && fake.Calls == 2, "Rejected intent is durable without becoming unknown or replaying");
            var unknown = Intent();
            for (var i = 0; i < 2; i++)
            {
                try { await second.Call(unknown, "test/disconnect", new { }, CancellationToken.None); throw new Exception("Unknown accepted"); } catch (IOException) { checks++; }
            }
            Check(broker.Unknown == 1 && fake.Calls == 3, "Unconfirmed intent is held, never replayed");
            try { await second.Call(Intent(), "thread/goal/set", new { }, CancellationToken.None); throw new Exception("Mutation passed unknown fence"); }
            catch (InvalidOperationException) { checks++; }
            await second.Call(Intent(), "thread/goal/get", new { }, CancellationToken.None);
            Check(fake.Calls == 4, "Read-only reconciliation remains possible behind unknown fence");
        }
        Check(fake.Disposed, "Only broker shutdown disposes its owned native stream");
        var next = new Fake();
        await using (var broker = NativeBroker.Fixture(next, next, new Ledger(path), next.Initialize))
        {
            await broker.Ready;
            Check(broker.Unknown == 1 && broker.Position == 0, "New native epoch preserves old unknown intents, without replaying old events into live UI");
        }
        return checks;
    }
    private sealed class Fake : INative, IAsyncDisposable
    {
        public uint Pid => 123;
        public int Calls, Initializations, Replies;
        public bool Disposed, ResolveDuringReply;
        public TaskCompletionSource Started = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource<JsonElement> Release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public event Action<JsonElement>? Notification;
        public Task Initialize() { Initializations++; return Task.CompletedTask; }
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls++; Started.TrySetResult();
            if (method == "test/reject") throw new NativeRejected(method);
            if (method == "test/disconnect") throw new IOException("Diagnostic native disconnect");
            return method == "test/slow" ? await Release.Task.WaitAsync(stop) : JsonSerializer.SerializeToElement(new { ok = true });
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop)
        {
            Replies++;
            if (ResolveDuringReply) Emit("serverRequest/resolved", new { threadId = "thread", requestId = id });
            return Task.CompletedTask;
        }
        public void Emit(string method, object parameters) => Notification?.Invoke(JsonSerializer.SerializeToElement(new { method, @params = parameters }));
        public void Request(object id, string thread, string turn) => Notification?.Invoke(JsonSerializer.SerializeToElement(new { id,
            method = "item/commandExecution/requestApproval", @params = new { threadId = thread, turnId = turn, itemId = "item" } }));
        public ValueTask DisposeAsync() { Disposed = true; return ValueTask.CompletedTask; }
    }
}
