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
        var policy = template with { StateDirectory = root, WorkspaceRoot = workspaces, StartSpacingSeconds = 1, OwnerFullAccess = true };
        using var ledger = new Ledger(Path.Combine(root, "joined.db"));
        ledger.Bind(new Binding(policy.ChatId, 42, "LG", workspaces + "\\lg-magic", "exact-native-id"));
        var native = new FakeNative(); var bot = new FakeBot(policy, native);
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var running = new Router(policy, ledger, bot, native).Run(stop.Token);
        try { await bot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(15)); }
        finally { stop.Cancel(); try { await running; } catch (OperationCanceledException) { } }
        Check(native.Started == 1 && native.Steered == 1, "Joined routing starts once and steers exact active turn");
        Check(native.LastProfile == ":danger-full-access" && native.LastApproval == "never", "Owner full-access profile survives exact resume");
        Check(native.SteerTurn == "turn-1" && native.LastInput!.Contains("second owner message") && !native.LastInput.Contains("Telegram owner"), "Steering expectedTurnId and plain input preserved without audit header");
        Check(native.Called.All(m => !m.Contains("queue", StringComparison.OrdinalIgnoreCase)), "No queue fallback");
        Check(bot.Sends == 1 && bot.Answers == 5 && bot.Edits >= 1, "One rolling progress message; complete long final answer split separately");
        Check(bot.Last!.Length <= 3900 && bot.Last.Contains("Done (") && bot.Last.Contains("FINAL-OK"), "Bounded final tail/footer survives tool output");
        Check(!bot.Last.Contains("STALE-EVENT"), "Stale-turn output cannot enter current bubble");
        Check(ledger.Pending().Count == 0 && ledger.Unknown == 0, "Joined ledger acknowledges once without uncertain effects");
        var saved = ledger.Get("bubble/exact-native-id")!.Value;
        Check(saved.GetProperty("message").GetInt32() == 900 && !saved.GetProperty("busy").GetBoolean(), "Bubble receipt and terminal state durable");

        var appRoot = Path.Combine(root, "native-origin"); Directory.CreateDirectory(appRoot);
        using (var appLedger = new Ledger(Path.Combine(appRoot, "router.db")))
        {
            appLedger.Bind(new Binding(policy.ChatId, 42, "LG", workspaces + "\\lg-magic", "exact-native-id"));
            appLedger.Put("bubble/exact-native-id", new { tail = "old completed turn", message = 900, sendUnknown = false, held = false, busy = false, status = "Done", elapsedMs = 100 });
            var appNative = new FakeNative { NativeOriginOnly = true }; var appBot = new FakeBot(policy, appNative);
            using var appStop = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            var appRun = new Router(policy with { StateDirectory = appRoot }, appLedger, appBot, appNative).Run(appStop.Token);
            try { await appBot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(12)); }
            finally { appStop.Cancel(); try { await appRun; } catch (OperationCanceledException) { } }
            Check(appNative.Started == 0 && appNative.Steered == 0, "Native-origin events cause no router model start or steering");
            Check(appBot.Sends == 1 && appBot.Answers == 1 && appBot.Edits >= 1, "Native-origin response gets one progress bubble plus final, preserving earlier response");
            Check(appBot.Last!.Contains("↪ Have you updated the source? Pushed?") && !appBot.Last.Contains("Native input:"), "Native user input appears with compact Telegram prefix");
            Check(appBot.Last.Contains("MCP fixture/inspect") && appBot.Last.Contains("exit 0") && !appBot.Last.Contains("TOOL-OUTPUT"), "Tool actions/results stay visible; raw output remains private in native history");
            Check(!appBot.Last.Contains("FOREIGN-INPUT") && !appBot.Last.Contains("STALE-INPUT") && !appBot.Last.Contains("PRIVATE-"), "Foreign/stale events and private attachment/tool fields are not reflected");
            Check(appBot.Last.Split("Have you updated the source? Pushed?").Length == 2, "Repeated completed input item is displayed once");
            Check(appBot.Last.Length <= 3900 && appBot.Last.Contains("Done (") && appLedger.Unknown == 0, "Native-origin terminal footer and receipts remain bounded/durable");
            Check(appNative.Called.Count(m => m == "remoteControl/status/read") == 1 && appBot.Last.Contains("Remote Control: disabled") && appBot.Last.Contains("Phone round trip"),
                "Authenticated remote command reads exact process once; foreign sender denied, no connection inference");
            Check(appBot.RemoteMenuVerified && appNative.Started == 0 && appBot.Sends == 1 && !appLedger.Get("bubble/exact-native-id")!.Value.GetProperty("held").GetBoolean(),
                "Remote diagnostic registered/read back and amends existing bubble without inference or held session");
        }
        foreach (var mode in new[] { "missing", "foreign", "malformed" })
        {
            var receiptRoot = Path.Combine(root, "steer-receipt-" + mode); Directory.CreateDirectory(receiptRoot);
            using var receiptLedger = new Ledger(Path.Combine(receiptRoot, "router.db"));
            receiptLedger.Bind(new Binding(policy.ChatId, 42, "LG", workspaces + "\\lg-magic", "exact-native-id"));
            var receiptNative = new FakeNative { BadSteerReceipt = mode }; var receiptBot = new FakeBot(policy, receiptNative);
            using var receiptStop = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            var receiptRun = new Router(policy with { StateDirectory = receiptRoot }, receiptLedger, receiptBot, receiptNative).Run(receiptStop.Token);
            try { await receiptBot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(12)); }
            finally { receiptStop.Cancel(); try { await receiptRun; } catch (OperationCanceledException) { } }
            Check(receiptNative.Started == 1 && receiptNative.Steered == 1 && receiptLedger.Get("bubble/exact-native-id")!.Value.GetProperty("held").GetBoolean(), "Unverified steering receipt holds exact input, without replay or new turn: " + mode);
            Check(!receiptBot.Last!.Contains("New owner message steered") && receiptBot.Last.Contains("not confirmed"), "Unverified steering is not described as accepted: " + mode);
        }

        var newRoot = Path.Combine(root, "new-provision"); Directory.CreateDirectory(newRoot);
        using (var creation = new Ledger(Path.Combine(newRoot, "creation.db")))
        {
            var bootstrap = new FakeNative(); var creationBot = new FakeBot(policy, bootstrap, provisioningOnly: true);
            using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            var run = new Router(policy with { StateDirectory = newRoot, OwnerFullAccess = false }, creation, creationBot, bootstrap).Run(cancel.Token);
            try { await creationBot.FirstSent.Task.WaitAsync(TimeSpan.FromSeconds(5)); }
            finally { cancel.Cancel(); try { await run; } catch (OperationCanceledException) { } }
            Check(bootstrap.Called.Take(3).SequenceEqual(new[] { "thread/start", "thread/inject_items", "thread/read" }), "New native ID checkpoint/readback precedes Telegram binding");
            Check(bootstrap.Started == 0 && creation.Bindings().Count == 1 && creationBot.CreatedTopics == 1, "Provisioning persists history without inference or duplicate topics");
            Check(bootstrap.LastProfile == ":workspace" && bootstrap.LastApproval == "on-request", "Restricted default does not inherit owner full access");
        }

        var mismatchRoot = Path.Combine(root, "profile-mismatch"); Directory.CreateDirectory(mismatchRoot);
        using (var mismatch = new Ledger(Path.Combine(mismatchRoot, "mismatch.db")))
        {
            mismatch.Bind(new Binding(policy.ChatId, 42, "LG", workspaces + "\\lg-magic", "exact-native-id"));
            var wrong = new FakeNative { MisreportProfile = true }; var wrongBot = new FakeBot(policy, wrong);
            try { await new Router(policy with { StateDirectory = mismatchRoot }, mismatch, wrongBot, wrong).Run(CancellationToken.None); throw new Exception("Security mismatch accepted"); }
            catch (InvalidOperationException)
            {
                Check(wrong.Started == 0 && wrongBot.Sends == 0 && wrongBot.CreatedTopics == 0, "Observed permission mismatch stops before model or Telegram effects");
            }
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
        public string? LastProfile, LastApproval;
        public bool MisreportProfile;
        public bool NativeOriginOnly;
        public string? BadSteerReceipt;
        public TaskCompletionSource Ready { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private void Event(string method, object parameters) => Notification?.Invoke(Json(new { method, @params = parameters }));
        public void NativeBurst()
        {
            Event("turn/started", new { threadId = "exact-native-id", turn = new { id = "native-turn" } });
            var input = new { threadId = "exact-native-id", turnId = "native-turn", item = new { id = "native-user", type = "userMessage", content = new object[] {
                new { type = "text", text = "Have you updated the source? Pushed?" }, new { type = "localImage", path = "PRIVATE-PATH" } } } };
            Event("item/completed", input); Event("item/completed", input);
            Event("item/completed", new { threadId = "foreign-thread", turnId = "native-turn", item = new { id = "foreign", type = "userMessage", content = new[] { new { type = "text", text = "FOREIGN-INPUT" } } } });
            Event("item/completed", new { threadId = "exact-native-id", turnId = "old-turn", item = new { id = "old", type = "userMessage", content = new[] { new { type = "text", text = "STALE-INPUT" } } } });
            Event("item/started", new { threadId = "exact-native-id", turnId = "native-turn", item = new { id = "native-tool", type = "mcpToolCall", server = "fixture", tool = "inspect", status = "inProgress", arguments = "PRIVATE-ARGS" } });
            Event("item/commandExecution/outputDelta", new { threadId = "exact-native-id", turnId = "native-turn", itemId = "cmd", delta = "TOOL-OUTPUT" });
            Event("item/completed", new { threadId = "exact-native-id", turnId = "native-turn", item = new { id = "cmd", type = "commandExecution", status = "completed", exitCode = 0 } });
            Event("item/completed", new { threadId = "exact-native-id", turnId = "native-turn", item = new { id = "reply", type = "agentMessage", text = "NATIVE-FINAL" } });
            Event("turn/completed", new { threadId = "exact-native-id", turn = new { id = "native-turn", status = "completed" } });
        }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Called.Add(method); var args = Json(parameters);
            switch (method)
            {
                case "thread/start":
                case "thread/resume":
                    LastProfile = args.GetProperty("permissions").GetString(); LastApproval = args.GetProperty("approvalPolicy").GetString();
                    return Task.FromResult(Json(new { cwd = args.GetProperty("cwd").GetString(), approvalPolicy = LastApproval, approvalsReviewer = "user",
                        sandbox = new { type = !MisreportProfile && LastProfile == ":danger-full-access" ? "dangerFullAccess" : "workspaceWrite" }, thread = new { id = "exact-native-id" } }));
                case "thread/inject_items": return Task.FromResult(Json(new { }));
                case "thread/read": return Task.FromResult(Json(new { thread = new { id = "exact-native-id" } }));
                case "thread/goal/get": return Task.FromResult(Json(new { goal = (object?)null }));
                case "remoteControl/status/read":
                    if (effect) throw new Exception("Remote status became an effect");
                    return Task.FromResult(Json(new { status = "disabled", serverName = "PRIVATE-HOST", installationId = "PRIVATE-INSTALLATION", environmentId = (string?)null }));
                case "turn/start":
                    Started++; Event("turn/started", new { threadId = "exact-native-id", turn = new { id = "turn-1" } });
                    Event("item/started", new { threadId = "exact-native-id", turnId = "turn-1", item = new { id = "tool", type = "commandExecution", command = "whoami /user" } });
                    Event("item/agentMessage/delta", new { threadId = "exact-native-id", turnId = "turn-1", itemId = "agent", delta = "FIRST" });
                    Ready.TrySetResult(); return Task.FromResult(Json(new { turn = new { id = "turn-1" } }));
                case "turn/steer":
                    Steered++; SteerTurn = args.GetProperty("expectedTurnId").GetString(); LastInput = args.GetProperty("input").GetRawText();
                    if (BadSteerReceipt != null) return Task.FromResult(BadSteerReceipt switch { "missing" => Json(new { }), "foreign" => Json(new { turnId = "wrong" }), _ => Json(new { turnId = 1 }) });
                    Event("item/agentMessage/delta", new { threadId = "exact-native-id", turnId = "turn-1", itemId = "agent", delta = new string('x', 18000) + " FINAL-OK" });
                    Event("item/agentMessage/delta", new { threadId = "exact-native-id", turnId = "old-turn", itemId = "old", delta = "STALE-EVENT" });
                    Event("item/completed", new { threadId = "exact-native-id", turnId = "turn-1", item = new { id = "agent", type = "agentMessage", phase = "final_answer", text = "FIRST" + new string('x', 18000) + " FINAL-OK" } });
                    Event("turn/completed", new { threadId = "exact-native-id", turn = new { id = "turn-1", status = "completed" } });
                    return Task.FromResult(Json(new { turnId = "turn-1" }));
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
        public int Answers;
        public bool RemoteMenuVerified;
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
                case "getMyCommands": RemoteMenuVerified = menus.EnumerateArray().Any(c => c.GetProperty("command").GetString() == "remote"); return menus;
                case "getChat": return Json(new { is_forum = true });
                case "getChatMember": return Json(new { status = "administrator", can_manage_topics = true });
                case "createForumTopic": CreatedTopics++; return Json(new { message_thread_id = 42 });
                case "getUpdates":
                    if (provisioningOnly) { await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>()); }
                    var count = Interlocked.Increment(ref polls);
                    if (native.NativeOriginOnly)
                    {
                        if (count == 1)
                        {
                            native.NativeBurst();
                            return Json(new[] { Update(103, policy.OwnerId + 1, "/remote"), Update(104, policy.OwnerId, "/remote") });
                        }
                        await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>());
                    }
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
            Sends++; Last = text; FirstSent.TrySetResult();
            if (native.NativeOriginOnly && text.Contains("NATIVE-FINAL") && text.Contains("Done (")) Completed.TrySetResult();
            return Task.FromResult(Json(new { message_id = 900 }));
        }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        {
            if (message != 900) throw new Exception("Wrong bubble receipt");
            Edits++; Last = text;
            if (native.NativeOriginOnly ? text.Contains("NATIVE-FINAL") && text.Contains("Done (") :
                native.BadSteerReceipt != null ? text.Contains("Held — input 101 not confirmed") : text.Contains("Done (")) Completed.TrySetResult();
            return Task.CompletedTask;
        }
        public Task<JsonElement> SendAnswer(long chat, int topic, AnswerPart part, CancellationToken stop)
        { Answers++; return Task.FromResult(Json(new { message_id = 1000 + Answers })); }
    }
}
