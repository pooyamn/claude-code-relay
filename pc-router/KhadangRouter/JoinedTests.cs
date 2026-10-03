using System.Text.Json;

namespace KhadangRouter;

public static class JoinedTests
{
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        var workspaces = OperatingSystem.IsWindows() ? Path.Combine(root, "workspaces") : "C:\\Workspaces";
        if (OperatingSystem.IsWindows()) Directory.CreateDirectory(Path.Combine(workspaces, "lg-magic"));
        var policy = template with { StateDirectory = root, WorkspaceRoot = workspaces, StartSpacingSeconds = 1 };
        using var ledger = new Ledger(Path.Combine(root, "joined.db"));
        ledger.Bind(new Binding(policy.ChatId, 42, "LG", workspaces + "\\lg-magic", "exact-native-id"));
        var native = new FakeNative(); var bot = new FakeBot(policy, native);
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var running = new Router(policy, ledger, bot, native).Run(stop.Token);
        try { await bot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(15)); }
        finally { stop.Cancel(); try { await running; } catch (OperationCanceledException) { } }
        Check(native.Started == 1 && native.Steered == 1, "Joined routing starts once and steers exact active turn");
        Check(native.SteerTurn == "turn-1" && native.LastInput!.Contains("second owner message"), "Steering expectedTurnId and input preserved");
        Check(native.Called.All(m => !m.Contains("queue", StringComparison.OrdinalIgnoreCase)), "No queue fallback");
        Check(bot.Sends == 1 && bot.Edits >= 1, "One rolling text message, final edit in place");
        Check(bot.Last!.Length <= 3900 && bot.Last.Contains("Done (") && bot.Last.Contains("FINAL-OK"), "Bounded final tail/footer survives tool output");
        Check(!bot.Last.Contains("STALE-EVENT"), "Stale-turn output cannot enter current bubble");
        Check(ledger.Pending().Count == 0 && ledger.Unknown == 0, "Joined ledger acknowledges once without uncertain effects");
        var saved = ledger.Get("bubble/exact-native-id")!.Value;
        Check(saved.GetProperty("message").GetInt32() == 900 && !saved.GetProperty("busy").GetBoolean(), "Bubble receipt and terminal state durable");

        var newRoot = Path.Combine(root, "new-provision"); Directory.CreateDirectory(newRoot);
        using (var creation = new Ledger(Path.Combine(newRoot, "creation.db")))
        {
            var bootstrap = new FakeNative(); var creationBot = new FakeBot(policy, bootstrap, provisioningOnly: true);
            using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            var run = new Router(policy with { StateDirectory = newRoot }, creation, creationBot, bootstrap).Run(cancel.Token);
            try { await creationBot.FirstSent.Task.WaitAsync(TimeSpan.FromSeconds(5)); }
            finally { cancel.Cancel(); try { await run; } catch (OperationCanceledException) { } }
            Check(bootstrap.Called.Take(3).SequenceEqual(new[] { "thread/start", "thread/inject_items", "thread/read" }), "New native ID checkpoint/readback precedes Telegram binding");
            Check(bootstrap.Started == 0 && creation.Bindings().Count == 1 && creationBot.CreatedTopics == 1, "Provisioning persists history without inference or duplicate topics");
        }

        // A known crash boundary must never create another thread/topic.
        var crashRoot = Path.Combine(root, "creation-crash"); Directory.CreateDirectory(crashRoot);
        using var uncertain = new Ledger(Path.Combine(crashRoot, "crash.db"));
        uncertain.Put("lg-provision", new { phase = "creating-topic", threadId = "already-created" });
        var fake = new FakeNative(); var fakeBot = new FakeBot(policy, fake);
        try { await new Router(policy with { StateDirectory = crashRoot }, uncertain, fakeBot, fake).Run(CancellationToken.None); throw new Exception("Creation replay accepted"); }
        catch (InvalidOperationException)
        {
            Check(!fake.Called.Contains("thread/start") && fakeBot.CreatedTopics == 0, "Creation crash stops before duplicate external actions");
        }
        return checks;
    }

    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    private sealed class FakeNative : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification;
        public List<string> Called { get; } = new();
        public int Started, Steered;
        public string? SteerTurn, LastInput;
        public TaskCompletionSource Ready { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private void Event(string method, object parameters) => Notification?.Invoke(Json(new { method, @params = parameters }));
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Called.Add(method); var args = Json(parameters);
            switch (method)
            {
                case "thread/start": return Task.FromResult(Json(new { cwd = args.GetProperty("cwd").GetString(), approvalPolicy = "on-request", approvalsReviewer = "user",
                    sandbox = new { type = "workspaceWrite" }, thread = new { id = "exact-native-id" } }));
                case "thread/inject_items": return Task.FromResult(Json(new { }));
                case "thread/read": return Task.FromResult(Json(new { thread = new { id = "exact-native-id" } }));
                case "thread/resume": return Task.FromResult(Json(new { cwd = args.GetProperty("cwd").GetString(), approvalPolicy = "on-request", approvalsReviewer = "user",
                    sandbox = new { type = "workspaceWrite" }, thread = new { id = "exact-native-id" } }));
                case "turn/start":
                    Started++; Event("turn/started", new { threadId = "exact-native-id", turn = new { id = "turn-1" } });
                    Event("item/started", new { threadId = "exact-native-id", turnId = "turn-1", item = new { id = "tool", type = "commandExecution", command = "whoami /user" } });
                    Event("item/agentMessage/delta", new { threadId = "exact-native-id", turnId = "turn-1", itemId = "agent", delta = "FIRST" });
                    Ready.TrySetResult(); return Task.FromResult(Json(new { turn = new { id = "turn-1" } }));
                case "turn/steer":
                    Steered++; SteerTurn = args.GetProperty("expectedTurnId").GetString(); LastInput = args.GetProperty("input").GetRawText();
                    Event("item/agentMessage/delta", new { threadId = "exact-native-id", turnId = "turn-1", itemId = "agent", delta = new string('x', 18000) + " FINAL-OK" });
                    Event("item/agentMessage/delta", new { threadId = "exact-native-id", turnId = "old-turn", itemId = "old", delta = "STALE-EVENT" });
                    Event("turn/completed", new { threadId = "exact-native-id", turn = new { id = "turn-1", status = "completed" } });
                    return Task.FromResult(Json(new { }));
                default: throw new InvalidOperationException("Unexpected fake native method " + method);
            }
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => Task.CompletedTask;
    }
    private sealed class FakeBot(RouterPolicy policy, FakeNative native, bool provisioningOnly = false) : IBot
    {
        private int polls;
        private JsonElement menus;
        public int Sends, Edits, CreatedTopics;
        public string? Last;
        public TaskCompletionSource FirstSent { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Completed { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private object Update(int id, long sender, string text) => new { update_id = id, message = new {
            from = new { id = sender, is_bot = false }, chat = new { id = policy.ChatId, is_forum = true }, message_id = id,
            message_thread_id = 42, text } };
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            switch (method)
            {
                case "setMyCommands": menus = Json(parameters).GetProperty("commands").Clone(); return Json(true);
                case "getMyCommands": return menus;
                case "getChat": return Json(new { is_forum = true });
                case "getChatMember": return Json(new { status = "administrator", can_manage_topics = true });
                case "createForumTopic": CreatedTopics++; return Json(new { message_thread_id = 42 });
                case "getUpdates":
                    if (provisioningOnly) { await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>()); }
                    var count = Interlocked.Increment(ref polls);
                    if (count == 1) return Json(new[] { Update(100, policy.OwnerId, "first owner message") });
                    if (count == 2)
                    {
                        await native.Ready.Task.WaitAsync(stop); await FirstSent.Task.WaitAsync(stop);
                        return Json(new[] { Update(101, policy.OwnerId, "second owner message"), Update(102, policy.OwnerId + 1, "unauthorized") });
                    }
                    await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>());
                default: throw new InvalidOperationException("Unexpected fake bot method " + method);
            }
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        {
            Sends++; Last = text; FirstSent.TrySetResult(); return Task.FromResult(Json(new { message_id = 900 }));
        }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        {
            if (message != 900) throw new Exception("Wrong bubble receipt");
            Edits++; Last = text; if (text.Contains("Done (")) Completed.TrySetResult(); return Task.CompletedTask;
        }
    }
}
