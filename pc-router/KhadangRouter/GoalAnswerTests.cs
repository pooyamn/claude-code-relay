using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

// Goal continuations share a turn, but each authoritative final is an answer.
public static class GoalAnswerTests
{
    public static async Task<int> Run(string root, RouterPolicy policy)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        var notify = typeof(Router).GetMethod("OnNative", flags)!;
        var flush = typeof(Router).GetMethod("FlushBubble", flags)!;
        foreach (var failure in new[] { 0, 429, -1 })
        {
            using var ledger = new Ledger(Path.Combine(root, "goal-answers-" + failure + ".db"));
            var binding = new Binding(policy.ChatId, 42, "Goal answers", policy.WorkspaceRoot + "\\lg-magic", "goal-answer-" + failure);
            var bot = new Bot(); var native = new Native(); var router = new Router(policy, ledger, bot, native);
            var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
            var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new object[] { binding.Address });
            void Event(string method, object parameters) => notify.Invoke(router, new[] { (object)JsonSerializer.SerializeToElement(new { method, @params = parameters }) });
            Task Flush() => (Task)flush.Invoke(router, new[] { session, CancellationToken.None })!;
            void Final(string id, string text, string phase = "final_answer") => Event("item/completed", new {
                threadId = binding.ThreadId, turnId = "same-turn", item = new { id, type = "agentMessage", phase, text } });
            Event("turn/started", new { threadId = binding.ThreadId, turn = new { id = "same-turn" } });
            Event("thread/goal/updated", new { threadId = binding.ThreadId, goal = new { threadId = binding.ThreadId, objective = "Keep working",
                status = "active", tokensUsed = 1, timeUsedSeconds = 1, createdAt = 1, updatedAt = 1 } });
            await Flush(); var bubble = bot.BubbleId;
            Final("commentary", "Still investigating", "commentary"); await Flush();
            Check(bot.Answers.Count == 0, "Commentary remains in the goal bubble");
            Final("first", "**First result**\n\n| Route | Status |\n| --- | --- |\n| DUT | Ready |"); bot.Failure = failure;
            await Task.WhenAll(Flush(), Flush());
            if (failure == -1)
            {
                Check(bot.Attempts == 1 && bot.Answers.Count == 0, "Unknown goal answer send is never automatically retried");
                var unknown = ledger.Get("bubble/" + binding.ThreadId)!.Value;
                Check(unknown.GetProperty("held").GetBoolean() && unknown.GetProperty("pendingAnswers")[0].GetProperty("Parts")[0].GetProperty("SendUnknown").GetBoolean(), "Unknown goal answer has a durable hold");
                var replacement = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
                typeof(Router).GetMethod("RestorePendingBubbles", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, new[] { replacement, (object)unknown });
                Check((bool)type.GetField("Held")!.GetValue(replacement)!, "Restart retains unknown-answer hold");
                continue;
            }
            Check(bot.Answers.Count == 1 && bot.Answers[0].RichHtml!.Contains("<b>First result</b>") && bot.Answers[0].RichHtml!.Contains("<table"), "Native table final is delivered before the goal or turn ends");
            Check((bool)type.GetField("Busy")!.GetValue(session)! && bot.Progress.Contains("Working (") && bot.BubbleId == bubble && bot.BubbleSends == 1, "Same rolling bubble remains working after a clean goal reply");
            Check(bot.Answers[0].Entities.All(e => e.type != "pre"), "Clean goal prose is outside the code block");
            Final("first", "Duplicate result"); Final("second", "Second result"); await Flush(); await Flush();
            Check(bot.Answers.Count == 2 && bot.Answers[^1].Text == "Second result", "Two explicit finals in one turn are separate, deduplicated messages");
            var saved = ledger.Get("bubble/" + binding.ThreadId)!.Value;
            var restored = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
            type.GetField("Turn")!.SetValue(restored, "same-turn");
            typeof(Router).GetMethod("RestorePendingBubbles", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, new[] { restored, (object)saved });
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, restored, new object[] { binding.Address });
            Final("second", "Replayed after reconnect");
            Check(ledger.Get("bubble/" + binding.ThreadId)!.Value.GetProperty("lastAnswer").GetString() == "Second result", "Restart dedup retains the last handoff answer");
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new object[] { binding.Address });
            Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "same-turn", status = "completed" } });
            await Flush(); Check(bot.Answers.Count == 2, "Later turn completion does not resend already-delivered goal finals");
            Check(failure != 429 || bot.Attempts == 3, "Known Telegram throttle retries only the rejected part");
        }
        // Actual October 7 failure: "Progress ?" was steered into an active
        // goal and Codex answered in commentary, not final_answer.
        foreach (var failure in new[] { 0, 429, -1 })
        {
            using var ledger = new Ledger(Path.Combine(root, "goal-steering-" + failure + ".db"));
            var binding = new Binding(policy.ChatId, 42, "Goal steering", policy.WorkspaceRoot + "\\lg-magic", "goal-steering-" + failure);
            var bot = new Bot(); var native = new Native(); var router = new Router(policy, ledger, bot, native);
            var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
            var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new object[] { binding.Address });
            void Event(string method, object parameters) => notify.Invoke(router, new[] { (object)JsonSerializer.SerializeToElement(new { method, @params = parameters }) });
            Task Flush() => (Task)flush.Invoke(router, new[] { session, CancellationToken.None })!;
            void Message(string id, string text, string phase = "commentary", string turn = "continuing") => Event("item/completed", new {
                threadId = binding.ThreadId, turnId = turn, item = new { id, type = "agentMessage", phase, text } });
            void Input(string id, string text) => Event("item/completed", new { threadId = binding.ThreadId, turnId = "continuing",
                item = new { id, type = "userMessage", content = new[] { new { type = "text", text } } } });
            Event("turn/started", new { threadId = binding.ThreadId, turn = new { id = "continuing" } });
            Event("thread/goal/updated", new { threadId = binding.ThreadId, goal = new { threadId = binding.ThreadId, objective = "Recover source",
                status = "active", tokensUsed = 1, timeUsedSeconds = 1, createdAt = 1, updatedAt = 1 } });
            Input("internal", "<codex_internal_context source=\"goal\">Continue the goal</codex_internal_context>");
            Message("background", "Recovering clock registers"); await Flush();
            Check(bot.Answers.Count == 0, "Goal continuation/background commentary remains in the rolling bubble");
            Event("item/started", new { threadId = binding.ThreadId, turnId = "continuing", item = new { id = "already-streaming", type = "agentMessage" } });
            Event("item/agentMessage/delta", new { threadId = binding.ThreadId, turnId = "continuing", itemId = "already-streaming", delta = "Old progress" });
            Input("human-progress", "Progress ?"); Input("human-progress", "Duplicate echo");
            Message("already-streaming", "Old progress finished"); await Flush();
            Check(bot.Answers.Count == 0 && (bool)type.GetField("GoalReplyPending")!.GetValue(session)!, "In-flight prose predating steering does not consume the pending reply");
            var saved = ledger.Get("bubble/" + binding.ThreadId)!.Value;
            var restored = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
            typeof(Router).GetMethod("RestorePendingBubbles", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, new[] { restored, (object)saved });
            Check((bool)type.GetField("GoalReplyPending")!.GetValue(restored)!, "Pending direct reply survives observer restart");
            Message("stale", "Wrong turn", turn: "old");
            Message("reply", "**About 60/100 (estimated).** 45 recovered modules compile and pass their checks.");
            bot.Failure = failure; await Task.WhenAll(Flush(), Flush());
            if (failure == -1)
            {
                Check(bot.Attempts == 1 && bot.Answers.Count == 0 && ledger.Get("bubble/" + binding.ThreadId)!.Value.GetProperty("held").GetBoolean(), "Uncertain commentary reply is durably held without retry");
                continue;
            }
            Check(bot.Answers.Count == 1 && bot.Answers[0].Text.StartsWith("About 60/100") && bot.Answers[0].Entities.Any(e => e.type == "bold"), "Real commentary steering answer reaches clean Telegram prose before goal completion");
            Check((bool)type.GetField("Busy")!.GetValue(session)! && bot.BubbleSends == 1 && bot.Progress.Contains("Working ("), "Steering reply does not stop the goal or create another working bubble");
            Message("reply", "Duplicate reply"); Input("human-progress", "Duplicate after delivery"); Message("later-background", "More background work"); await Flush();
            Check(bot.Answers.Count == 1, "Duplicate input/output echoes and later background work do not send extra clean replies");
            Input("second-human", "Another question"); Message("explicit-reply", "Actual final", "final_answer"); await Flush();
            Check(bot.Answers.Count == 2 && bot.Answers[^1].Text == "Actual final", "Explicit final consumes the direct reply boundary exactly once");
            Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "continuing", status = "completed" } }); await Flush();
            Check(bot.Answers.Count == 2, "Turn completion never resends direct goal replies");
        }
        return checks;
    }
    private sealed class Native : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true) => throw new Exception("No native effects");
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No replies");
    }
    private sealed class Bot : IBot
    {
        public int BubbleId = 900, BubbleSends, Attempts, Failure;
        public string Progress = "";
        public List<AnswerPart> Answers = [];
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No network");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        { BubbleSends++; Progress = text; return Task.FromResult(JsonSerializer.SerializeToElement(new { message_id = BubbleId })); }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        { if (message != BubbleId) throw new Exception("Bubble changed"); Progress = text; return Task.CompletedTask; }
        public Task<JsonElement> SendAnswer(long chat, int topic, AnswerPart part, CancellationToken stop)
        {
            Attempts++; var failure = Failure; Failure = 0;
            if (failure != 0) throw new TelegramFailure(failure == 429 ? 429 : 0, retryAfter: 1);
            Answers.Add(part); return Task.FromResult(JsonSerializer.SerializeToElement(new { message_id = 1000 + Answers.Count }));
        }
    }
}
