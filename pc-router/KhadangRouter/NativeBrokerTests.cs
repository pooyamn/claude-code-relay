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
        // Reproduce shutdown with a reply whose underlying write has not yet
        // settled. Closing the private journal early loses outcome custody.
        var draining = new Fake { BlockReplies = true, FailReplyAfterRelease = true };
        var drainPath = Path.Combine(root, "broker-reply-drain.db");
        var drainLedger = new Ledger(drainPath);
        var drainBroker = NativeBroker.Fixture(draining, draining, drainLedger, draining.Initialize);
        await drainBroker.Ready;
        using (var client = drainBroker.AttachFixture(() => { }))
        {
            draining.Request("drain", "thread", "turn");
            var reply = client.Reply(client.Requests().Single(), new { decision = "decline" });
            await draining.ReplyStarted.Task.WaitAsync(TimeSpan.FromSeconds(10));
            var shutdown = drainBroker.DisposeAsync().AsTask();
            await draining.DisposedSignal.Task.WaitAsync(TimeSpan.FromSeconds(10));
            var closedBeforeReplySettled = shutdown.IsCompleted;
            var sameDrain = ReferenceEquals(shutdown, drainBroker.DisposeAsync().AsTask());
            var journalStillOpen = drainLedger.Query("SELECT status FROM broker_replies").Single()[0] == "attempting";
            draining.ReplyRelease.TrySetResult();
            try { await reply; throw new Exception("Failed native write accepted"); } catch (IOException) { checks++; }
            await shutdown;
            Check(!closedBeforeReplySettled, "Broker shutdown must retain journal until every in-flight reply settles");
            Check(sameDrain && draining.Disposals == 1, "Concurrent shutdown waiters join one owner closure/drain");
            Check(journalStillOpen, "Private journal remains usable until actual reply settlement");
        }
        using (var reopened = new Ledger(drainPath))
            Check(reopened.Query("SELECT status FROM broker_replies").Single()[0] == "unknown",
                "Shutdown retains ambiguous reply evidence, not an abandoned attempting row");
        var cleanup = new Fake { BlockReplies = true, ResolveDuringReply = true };
        var cleanupPath = Path.Combine(root, "broker-reply-shutdown-cleanup.db");
        var cleanupBroker = NativeBroker.Fixture(cleanup, cleanup, new Ledger(cleanupPath), cleanup.Initialize);
        await cleanupBroker.Ready;
        using (var client = cleanupBroker.AttachFixture(() => { }))
        {
            cleanup.Request("cleanup", "thread", "turn");
            var reply = client.Reply(client.Requests().Single(), new { decision = "decline" });
            await cleanup.ReplyStarted.Task.WaitAsync(TimeSpan.FromSeconds(10));
            var shutdown = cleanupBroker.DisposeAsync().AsTask();
            await cleanup.DisposedSignal.Task.WaitAsync(TimeSpan.FromSeconds(10));
            cleanup.ReplyRelease.TrySetResult(); await reply; await shutdown;
        }
        using (var reopened = new Ledger(cleanupPath))
        {
            Check(reopened.Query("SELECT status FROM broker_replies").Single()[0] == "resolved-unattributed" &&
                reopened.Query("SELECT status FROM broker_requests").Single()[0] == "resolved", "Resolution arriving during shutdown remains cleanup, never accepted approval");
            Check(reopened.Query("SELECT frame FROM broker_events ORDER BY position").Count == 2, "Shutdown retains the final native resolution event before closing journal");
        }
        var global = new Fake(); var globalPath = Path.Combine(root, "broker-connection-request.db");
        var globalLedger = new Ledger(globalPath); BrokerRequest? pendingConnection = null;
        await using (var broker = NativeBroker.Fixture(global, global, globalLedger, global.Initialize))
        {
            await broker.Ready;
            using var client = broker.AttachFixture(() => { });
            var rejectedNonThreadRequest = false;
            try { global.ConnectionRequest("refresh"); }
            catch (Exception error) when (error is KeyNotFoundException or InvalidDataException) { rejectedNonThreadRequest = true; }
            Check(!rejectedNonThreadRequest, "Connection-scoped native request must not destroy event custody for missing threadId");
            var request = broker.Requests(connection: true).Single();
            Check(request.Thread == null && request.Turn == null && request.Epoch == broker.Epoch &&
                request.Frame.GetProperty("method").GetString() == "account/chatgptAuthTokens/refresh", "Global request keeps explicit connection scope and complete native frame");
            Check(client.Requests().Count == 0 && client.Events(0).Count == 1, "Thread approval inbox excludes connection requests while protected event custody retains them");
            try { await client.Reply(request, new { decision = "accept" }); throw new Exception("Forum path answered connection request"); }
            catch (InvalidDataException) { checks++; }
            var changedFrame = JsonSerializer.SerializeToElement(new { id = "refresh", method = "item/commandExecution/requestApproval", @params = new { threadId = "thread", turnId = "turn" } });
            try { await broker.Reply(request with { Frame = changedFrame }, new { }, connection: true); throw new Exception("Changed reviewed frame accepted"); }
            catch (InvalidDataException) { checks++; }
            Check(global.Replies == 0, "Scope/complete-frame forgery fails before native write");
            // Fake result only: no credential access/refresh/enrollment occurs.
            await broker.Reply(request, new { accessToken = "[inert-fixture-not-a-token]", chatgptAccountId = "inert-fixture" }, connection: true);
            Check(global.Replies == 1 && broker.Requests(connection: true).Count == 0 && broker.Unknown == 0,
                "Protected connection reply is consumed once without becoming a thread approval");
            try { await broker.Reply(request, new { }, connection: true); throw new Exception("Connection reply replayed"); }
            catch (InvalidDataException) { checks++; }
            global.Raw(new { method = "test/notificationWithoutParams" });
            Check(client.Events(0).Last().Frame.GetProperty("method").GetString() == "test/notificationWithoutParams", "Opaque valid notification without params remains retained");
            global.ConnectionRequest("pending"); pendingConnection = broker.Requests(connection: true).Single();
        }
        var globalNext = new Fake();
        await using (var broker = NativeBroker.Fixture(globalNext, globalNext, new Ledger(globalPath), globalNext.Initialize))
        {
            await broker.Ready;
            Check(broker.Requests(connection: true).Count == 0 && broker.Unknown == 1, "New connection invalidates old global requests and preserves unconfirmed submitted reply");
            try { await broker.Reply(pendingConnection!, new { }, connection: true); throw new Exception("Old connection request answered"); }
            catch (InvalidDataException) { Check(globalNext.Replies == 0, "Prior-epoch connection request cannot obtain a replacement reply"); }
        }
        foreach (var shape in new[] { "threadless-approval", "mixed-auth", "turn-without-thread" })
        {
            var invalid = new Fake(); var invalidLedger = new Ledger(Path.Combine(root, "broker-scope-" + shape + ".db"));
            await using var broker = NativeBroker.Fixture(invalid, invalid, invalidLedger, invalid.Initialize); await broker.Ready;
            var method = shape == "threadless-approval" ? "item/commandExecution/requestApproval" : "account/chatgptAuthTokens/refresh";
            object parameters = shape == "mixed-auth" ? new { threadId = "thread" } : shape == "turn-without-thread" ? new { turnId = "turn" } : new { };
            try { invalid.Raw(new { id = "invalid", method, @params = parameters }); throw new Exception("Mixed/missing native request scope accepted"); }
            catch (InvalidDataException) { Check(broker.Position == 0 && invalidLedger.Query("SELECT id FROM broker_requests").Count == 0,
                "Invalid scope rolls back event/request together: " + shape); }
        }
        return checks;
    }
    private sealed class Fake : INative, IAsyncDisposable
    {
        public uint Pid => 123;
        public int Calls, Initializations, Replies, Disposals;
        public bool Disposed, ResolveDuringReply, BlockReplies, FailReplyAfterRelease;
        public TaskCompletionSource Started = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource<JsonElement> Release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource ReplyStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource ReplyRelease = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource DisposedSignal = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public event Action<JsonElement>? Notification;
        public Task Initialize() { Initializations++; return Task.CompletedTask; }
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls++; Started.TrySetResult();
            if (method == "test/reject") throw new NativeRejected(method);
            if (method == "test/disconnect") throw new IOException("Diagnostic native disconnect");
            return method == "test/slow" ? await Release.Task.WaitAsync(stop) : JsonSerializer.SerializeToElement(new { ok = true });
        }
        public async Task Reply(JsonElement id, object result, CancellationToken stop)
        {
            Replies++;
            if (BlockReplies)
            {
                ReplyStarted.TrySetResult();
                // Deliberately ignore cancellation: disposal must drain actual
                // settlement, not infer it from a stop request or elapsed time.
                await ReplyRelease.Task;
                if (FailReplyAfterRelease) throw new IOException("Diagnostic unresolved write");
            }
            if (ResolveDuringReply) Emit("serverRequest/resolved", new { threadId = "thread", requestId = id });
        }
        public void Emit(string method, object parameters) => Notification?.Invoke(JsonSerializer.SerializeToElement(new { method, @params = parameters }));
        public void Request(object id, string thread, string turn) => Notification?.Invoke(JsonSerializer.SerializeToElement(new { id,
            method = "item/commandExecution/requestApproval", @params = new { threadId = thread, turnId = turn, itemId = "item" } }));
        public void ConnectionRequest(object id) => Notification?.Invoke(JsonSerializer.SerializeToElement(new { id,
            method = "account/chatgptAuthTokens/refresh", @params = new { reason = "unauthorized", previousAccountId = "inert-fixture" } }));
        public void Raw(object message) => Notification?.Invoke(JsonSerializer.SerializeToElement(message));
        public ValueTask DisposeAsync() { Disposals++; Disposed = true; DisposedSignal.TrySetResult(); return ValueTask.CompletedTask; }
    }
}
