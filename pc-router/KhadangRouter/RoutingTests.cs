using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

public static class RoutingTests
{
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);

    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        const long otherForum = -1004395661179, wholeGroup = -5238984877, pendingForum = -1009999;
        var directory = Path.Combine(root, "full-address-routing"); Directory.CreateDirectory(directory);
        var workspace = OperatingSystem.IsWindows() ? Path.Combine(directory, "workspaces") : "C:\\RoutingWorkspaces";
        if (OperatingSystem.IsWindows()) Directory.CreateDirectory(Path.Combine(workspace, "fixture"));
        var policy = template with { StateDirectory = directory, WorkspaceRoot = workspace, OwnerFullAccess = true,
            StartSpacingSeconds = 1, AdditionalChats = [new(otherForum), new(wholeGroup, false), new(pendingForum)] };
        var bindings = new[] {
            new Binding(policy.ChatId, 42, "Primary fixture", workspace + "\\fixture", "routing-primary"),
            new Binding(otherForum, 42, "Other forum fixture", workspace + "\\fixture", "routing-other"),
            new Binding(wholeGroup, 0, "Whole-group fixture", workspace + "\\fixture", "routing-group") };

        object Message(long chat, bool? forum, object? topic, long? sender = null, bool forward = false)
        {
            var chatData = new Dictionary<string, object> { ["id"] = chat };
            if (forum is { } value) chatData["is_forum"] = value;
            var message = new Dictionary<string, object> { ["chat"] = chatData,
                ["from"] = new { id = sender ?? policy.OwnerId, is_bot = false }, ["text"] = "fixture" };
            if (topic != null) message["message_thread_id"] = topic;
            if (forward) message["forward_origin"] = new { type = "user" };
            return message;
        }
        // Mac fixture storage is deliberately native /tmp; production policy
        // paths still must validate as Windows paths on both platforms.
        (policy with { StateDirectory = template.StateDirectory }).Validate(); policy.ValidateBindings(bindings);
        Check(policy.OwnerMessage(Json(Message(otherForum, true, 42))), "Explicit second forum admits only owner messages");
        Check(policy.OwnerMessage(Json(Message(wholeGroup, null, null))) && policy.TryAddress(Json(Message(wholeGroup, false, null)), out var group) && group == bindings[2].Address,
            "Basic group explicitly routes without a topic, with absent or false is_forum");
        Check(policy.TryAddress(Json(Message(otherForum, true, null)), out var general) && general == new TopicAddress(otherForum, 1), "Missing forum topic remains General, not whole-group");
        foreach (var invalid in new[] {
            Message(-1009876, true, 42), Message(otherForum, false, 42), Message(otherForum, null, 42),
            Message(wholeGroup, true, null), Message(wholeGroup, false, 1), Message(otherForum, true, 0),
            Message(otherForum, true, -1), Message(otherForum, true, "42"), Message(otherForum, true, 1.5),
            Message(otherForum, true, 42, policy.OwnerId + 1), Message(otherForum, true, 42, forward: true) })
            Check(!policy.OwnerMessage(Json(invalid)), "Unadmitted, malformed, forwarded or foreign input fails closed");
        foreach (var routes in new ChatRoute[][] { [new(policy.ChatId)], [new(otherForum), new(otherForum)], [new(1, false)], [new(wholeGroup, true)] })
        {
            try { (policy with { AdditionalChats = routes, StateDirectory = template.StateDirectory }).Validate(); throw new Exception("Invalid chat policy accepted"); }
            catch (InvalidDataException) { checks++; }
        }
        Check(!Json(Telegram.SendParameters(wholeGroup, 0, "fixture")).TryGetProperty("message_thread_id", out _), "Whole-group send omits Telegram message_thread_id, not zero or a fabricated topic");
        Check(Json(Telegram.SendParameters(otherForum, 42, "fixture")).GetProperty("message_thread_id").GetInt32() == 42, "Forum send retains exact topic");

        using (var ledger = new Ledger(Path.Combine(directory, "router.db")))
        {
            foreach (var binding in bindings)
            {
                ledger.Bind(binding);
                // Telegram message IDs are per chat: all three can legitimately
                // have message 900. Legacy primary receipt must still work.
                ledger.Put("bubble/" + binding.ThreadId, Receipt(binding, legacy: binding.Chat == policy.ChatId));
            }
            var native = new RoutingNative(policy, bindings); var bot = new RoutingBot(policy, bindings, ledger, native);
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            var run = new Router(policy, ledger, bot, native).Run(stop.Token);
            try { await bot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(15)); }
            finally { stop.Cancel(); try { await run; } catch (OperationCanceledException) { } }
            Check(native.Starts.Count == 3 && native.Steers.Count == 3 && bindings.All(b => native.Starts.ContainsKey(b.ThreadId) && native.Steers[b.ThreadId].GetProperty("expectedTurnId").GetString() == "same-turn-id"),
                "Same topic numbers across chats and whole-group input start/steer their own exact native sessions");
            Check(bindings.All(b => native.Starts[b.ThreadId].GetProperty("input").GetRawText().Contains("START-" + b.ThreadId) &&
                native.Steers[b.ThreadId].GetProperty("input").GetRawText().Contains("STEER-" + b.ThreadId)), "Owner input never leaks into the other forum's matching topic number");
            Check(bot.Sends == bindings.Length && bindings.All(b => bot.Edits.ContainsKey(b.Address)), "Every new response gets its own topic-addressed bubble");
            Check(bindings.All(b => bot.Edits[b.Address].Length <= 3900 && bot.Edits[b.Address].Contains("FINAL-" + b.ThreadId) && bot.Edits[b.Address].Contains("APP-" + b.ThreadId) &&
                bindings.Where(other => other != b).All(other => !bot.Edits[b.Address].Contains(other.ThreadId))), "Native app input, tools, final text and footer stay in the correct chat's rolling bubble");
            Check(bot.Menus.Keys.Order().SequenceEqual(bindings.Select(b => b.Chat).Order()) && bot.MenuReadbacks == 3, "Owner menus registered/read back per activated chat; inaccessible unbound chat untouched");
            Check(bot.CrossChatRepliesBeforeCorrect == 0 && native.Replies.Count == 2, "Approval and question nonces from one chat cannot be consumed from the other matching topic");
            Check(native.Replies.All(r => r.Id is 77 or 78) && native.Replies.Single(r => r.Id == 77).Result.GetProperty("decision").GetString() == "accept" &&
                native.Replies.Single(r => r.Id == 78).Result.GetProperty("answers").GetProperty("q").GetProperty("answers")[0].GetString() == "OWNER-CORRECT",
                "Only correct chat/thread/turn consumes exact native approval and answer");
            Check(ledger.Unknown == 0 && ledger.Pending().Count == 0 && bindings.All(b => ledger.Get("bubble/" + b.ThreadId)!.Value.GetProperty("chat").GetInt64() == b.Chat &&
                ledger.Get("bubble/" + b.ThreadId)!.Value.GetProperty("topic").GetInt32() == b.Topic), "Destinations, terminal bubbles and input receipts are durable without ambiguous replay");
        }

        // Invalid later rows and receipt destinations must stop before resuming
        // even the first valid row; no partial startup or new-thread fallback.
        foreach (var failure in new[] { "foreign", "shared-thread", "wrong-topic", "receipt-chat", "legacy-foreign" })
        {
            var path = Path.Combine(directory, failure); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "router.db")); ledger.Bind(bindings[0]);
            var second = failure switch {
                "foreign" => bindings[1] with { Chat = -1009876 },
                "shared-thread" => bindings[1] with { ThreadId = bindings[0].ThreadId },
                "wrong-topic" => bindings[2] with { Topic = 42 }, _ => bindings[1] };
            ledger.Bind(second);
            if (failure == "receipt-chat") ledger.Put("bubble/" + second.ThreadId, Receipt(second with { Chat = policy.ChatId }));
            if (failure == "legacy-foreign") ledger.Put("bubble/" + second.ThreadId, Receipt(second, legacy: true));
            var native = new RoutingNative(policy, bindings); var bot = new RoutingBot(policy, bindings, ledger, native);
            try { await new Router(policy with { StateDirectory = path }, ledger, bot, native).Run(CancellationToken.None); throw new Exception("Ambiguous registry accepted"); }
            catch (InvalidDataException) { Check(native.Resumes == 0 && bot.Menus.Count == 0 && bot.Sends == 0, "Whole registry validation precedes any native or bot startup effect: " + failure); }
        }
        return checks;
    }

    private static object Receipt(Binding binding, bool legacy = false)
    {
        var value = new Dictionary<string, object> { ["tail"] = "Fixture history", ["message"] = 900, ["sendUnknown"] = false,
            ["held"] = false, ["busy"] = false, ["status"] = "Done", ["elapsedMs"] = 0 };
        if (!legacy) { value["chat"] = binding.Chat; value["topic"] = binding.Topic; }
        return value;
    }

    private sealed class RoutingNative(RouterPolicy policy, Binding[] bindings) : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification;
        public int Resumes;
        public ConcurrentDictionary<string, JsonElement> Starts = new(), Steers = new();
        public ConcurrentBag<(int Id, JsonElement Result)> Replies = new();
        public TaskCompletionSource AllStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public void Event(string method, object parameters, int? id = null)
        {
            var frame = new Dictionary<string, object> { ["method"] = method, ["params"] = parameters };
            if (id != null) frame["id"] = id;
            Notification?.Invoke(Json(frame));
        }
        public void Requests()
        {
            Event("item/commandExecution/requestApproval", new { threadId = bindings[0].ThreadId, turnId = "same-turn-id", command = "fixture read" }, 77);
            Event("item/tool/requestUserInput", new { threadId = bindings[0].ThreadId, turnId = "same-turn-id", questions = new[] { new { id = "q", question = "Fixture choice?", isSecret = false } } }, 78);
        }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            var args = Json(parameters); var thread = args.GetProperty("threadId").GetString()!;
            switch (method)
            {
                case "thread/resume":
                    if (!args.GetProperty("excludeTurns").GetBoolean()) throw new Exception("Resume must not serialize full migrated history onto the bounded event transport");
                    Resumes++;
                    return Task.FromResult(Json(new { cwd = args.GetProperty("cwd").GetString(), approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user",
                        sandbox = new { type = policy.NativeSandboxType }, thread = new { id = thread } }));
                case "thread/goal/get": return Task.FromResult(Json(new { goal = (object?)null }));
                case "turn/start":
                    Starts[thread] = args;
                    Event("turn/started", new { threadId = thread, turn = new { id = "same-turn-id" } });
                    if (Starts.Count == bindings.Length) AllStarted.TrySetResult();
                    return Task.FromResult(Json(new { turn = new { id = "same-turn-id" } }));
                case "turn/steer":
                    Steers[thread] = args;
                    Event("item/completed", new { threadId = thread, turnId = "same-turn-id", item = new { id = "app", type = "userMessage", content = new[] { new { type = "text", text = "APP-" + thread } } } });
                    Event("item/started", new { threadId = thread, turnId = "same-turn-id", item = new { id = "tool", type = "commandExecution", command = "TOOL-" + thread } });
                    Event("item/completed", new { threadId = thread, turnId = "same-turn-id", item = new { id = "reply", type = "agentMessage", text = "FINAL-" + thread } });
                    Event("turn/completed", new { threadId = thread, turn = new { id = "same-turn-id", status = "completed" } });
                    return Task.FromResult(Json(new { turnId = "same-turn-id" }));
                default: throw new Exception("Unexpected routing native RPC: " + method);
            }
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) { Replies.Add((id.GetInt32(), Json(result))); return Task.CompletedTask; }
    }

    private sealed class RoutingBot(RouterPolicy policy, Binding[] bindings, Ledger ledger, RoutingNative native) : IBot
    {
        private int polls;
        public int Sends, MenuReadbacks, CrossChatRepliesBeforeCorrect;
        public ConcurrentDictionary<TopicAddress, string> Edits = new();
        public Dictionary<long, JsonElement> Menus = new();
        public TaskCompletionSource Completed = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private object Update(int id, Binding binding, string text, bool foreign = false)
        {
            var chat = new Dictionary<string, object> { ["id"] = binding.Chat };
            if (binding.Topic > 0) chat["is_forum"] = true;
            var message = new Dictionary<string, object> { ["chat"] = chat, ["from"] = new { id = foreign ? policy.OwnerId + 1 : policy.OwnerId, is_bot = false },
                ["message_id"] = id, ["text"] = text };
            if (binding.Topic > 0) message["message_thread_id"] = binding.Topic;
            return new { update_id = id, message };
        }
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            var args = Json(parameters);
            if (method == "setMyCommands") { Menus.Add(args.GetProperty("scope").GetProperty("chat_id").GetInt64(), args.GetProperty("commands").Clone()); return Json(true); }
            if (method == "getMyCommands") { MenuReadbacks++; return Menus[args.GetProperty("scope").GetProperty("chat_id").GetInt64()]; }
            if (method != "getUpdates") throw new Exception("Unexpected routing bot API: " + method);
            polls++;
            if (polls == 1) return Json(bindings.Select((b, i) => Update(100 + i, b, "START-" + b.ThreadId)).Concat(new[] {
                Update(103, bindings[1], "FOREIGN-SENDER", foreign: true), Update(104, bindings[0] with { Chat = -1009876 }, "FOREIGN-CHAT") }));
            if (polls == 2)
            {
                await native.AllStarted.Task.WaitAsync(stop); native.Requests();
                var bubble = ledger.Get("bubble/" + bindings[0].ThreadId)!.Value.GetProperty("tail").GetString()!;
                var approval = Regex.Match(bubble, @"/approve ([a-f0-9]{12})").Groups[1].Value;
                var question = Regex.Match(bubble, @"/answer ([a-f0-9]{12})").Groups[1].Value;
                if (approval.Length != 12 || question.Length != 12) throw new Exception("Native requests not reflected in exact bubble");
                return Json(new[] { Update(110, bindings[1], "/approve " + approval), Update(111, bindings[1], "/answer " + question + " q CROSS-CHAT") });
            }
            if (polls == 3)
            {
                // Wait on the durable dispatch state, not an arbitrary timer.
                while (ledger.Query("SELECT COUNT(*) FROM updates WHERE id IN (110,111) AND status='control'")[0][0] != "2") await Task.Delay(10, stop);
                CrossChatRepliesBeforeCorrect = native.Replies.Count;
                var bubble = ledger.Get("bubble/" + bindings[0].ThreadId)!.Value.GetProperty("tail").GetString()!;
                var approval = Regex.Match(bubble, @"/approve ([a-f0-9]{12})").Groups[1].Value;
                var question = Regex.Match(bubble, @"/answer ([a-f0-9]{12})").Groups[1].Value;
                return Json(new[] { Update(120, bindings[0], "/approve " + approval), Update(121, bindings[0], "/answer " + question + " q OWNER-CORRECT") }
                    .Concat(bindings.Select((b, i) => Update(122 + i, b, "STEER-" + b.ThreadId))));
            }
            await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>());
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        { Sends++; Observe(chat, text); return Task.FromResult(Json(new { message_id = 901 })); }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        {
            if (message is not (900 or 901)) throw new Exception("Unknown routing bubble ID"); Observe(chat, text);
            return Task.CompletedTask;
        }
        private void Observe(long chat, string text)
        {
            var binding = bindings.Single(b => b.Chat == chat); Edits[binding.Address] = text;
            if (bindings.All(b => Edits.TryGetValue(b.Address, out var tail) && tail.Contains("FINAL-" + b.ThreadId) && tail.Contains("Done ("))) Completed.TrySetResult();
        }
    }
}
