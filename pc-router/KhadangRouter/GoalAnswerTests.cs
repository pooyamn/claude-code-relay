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
            Final("first", "**First result**"); bot.Failure = failure;
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
            Check(bot.Answers.Count == 1 && bot.Answers[0].Text == "First result", "Final is delivered before the goal or turn ends");
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
