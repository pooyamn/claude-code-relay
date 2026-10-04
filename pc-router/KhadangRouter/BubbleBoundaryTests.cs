using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

// Exercise the real notification/editor boundary without polling, credentials,
// native processes or a model. Reflection avoids a test-only production API.
public static class BubbleBoundaryTests
{
    public static async Task<int> Run(string root, RouterPolicy policy)
    {
        var checks = 0;
        void Check(bool ok, string name) { if (!ok) throw new Exception(name); checks++; }
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var sessionType = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        var binding = new Binding(policy.ChatId, 42, "fixture", policy.WorkspaceRoot + "\\lg-magic", "bubble-fixture");
        var native = new FixtureNative(); var bot = new FixtureBot();
        using var ledger = new Ledger(Path.Combine(root, "bubble-boundaries.db"));
        var router = new Router(policy, ledger, bot, native);
        var constructor = sessionType.GetConstructors(flags | BindingFlags.Public).Single();
        var session = constructor.Invoke(constructor.GetParameters().Length == 1 ? new object[] { binding } : new object[] { binding, native });
        var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
        var keyType = sessions.GetType().GetGenericArguments()[0];
        sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new[] {
            keyType == typeof(int) ? (object)binding.Topic : binding.GetType().GetProperty("Address")!.GetValue(binding)! });
        var notify = typeof(Router).GetMethod("OnNative", flags)!;
        var flush = typeof(Router).GetMethod("FlushBubble", flags)!;
        void Event(string method, object parameters) => notify.Invoke(router, new[] { (object)Json(new { method, @params = parameters }) });
        void Start(string turn) => Event("turn/started", new { threadId = binding.ThreadId, turn = new { id = turn } });
        void Finish(string turn, string text)
        {
            Event("item/agentMessage/delta", new { threadId = binding.ThreadId, turnId = turn, itemId = turn, delta = text });
            Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = turn, status = "completed" } });
        }
        Task Flush() => (Task)flush.Invoke(router, new[] { session, CancellationToken.None })!;
        Start("first");
        bot.BeforeSend = () => { Finish("first", "FIRST-FINAL"); Start("second"); Finish("second", "SECOND-FINAL"); };
        await Flush(); // The first send receipt arrives after the second turn.
        await Flush(); // First message receives its final text, not second's.
        await Flush(); // Second response gets a distinct message.
        Check(bot.Sends == 2 && bot.Messages.Keys.SequenceEqual(new[] { 901, 902 }), "Separate response IDs despite a late first send receipt");
        Check(bot.Messages[901].Contains("FIRST-FINAL") && !bot.Messages[901].Contains("SECOND-FINAL") && bot.Messages[901].Contains("Done ("), "First final response survives editor/turn rollover race");
        Check(bot.Messages[902].Contains("SECOND-FINAL") && !bot.Messages[902].Contains("FIRST-FINAL"), "Second response cannot overwrite first message");
        var before = bot.Sends;
        Start("second"); await Flush();
        Check(bot.Sends == before && ledger.Get("bubble/" + binding.ThreadId)!.Value.GetProperty("status").GetString() == "Done", "Duplicate completed-turn start does not resurrect or rotate bubble");
        Start("third"); Finish("third", "THIRD-FINAL"); Start("fourth"); Finish("fourth", "FOURTH-FINAL");
        await Flush(); await Flush();
        Check(bot.Sends == 4 && bot.Messages[903].Contains("THIRD-FINAL") && bot.Messages[904].Contains("FOURTH-FINAL"), "Two turns completed between editor ticks both retain a new final message");
        Check(bot.Messages.Values.All(t => t.Length <= 3900), "Every per-response bubble stays within Telegram bounds");
        Check(bot.BubbleSends == bot.Sends && bot.BubbleEdits > 0, "Real rolling editor uses formatted send and amend paths");
        var response = (ResponseMessage)sessionType.GetField("Response")!.GetValue(session)!;
        response.LastRendered = ""; // Restart restores the message receipt, not this in-memory rendering cache.
        sessionType.GetField("Dirty")!.SetValue(session, true);
        var edits = bot.BubbleEdits;
        await Flush();
        Check(bot.Sends == 4 && bot.BubbleEdits == edits + 1 && response.Message == 904,
            "Restart restyles a retained bubble in place without a new message or model action");
        Start("unknown"); bot.UnknownSend = true; await Flush();
        Finish("unknown", "UNKNOWN-FINAL"); Start("after-unknown"); Finish("after-unknown", "NOT-REPLAYED"); await Flush();
        Check(bot.Sends == 5 && !bot.Messages.Values.Any(t => t.Contains("NOT-REPLAYED")), "Uncertain send is not replayed or bypassed by a later response");
        var saved = ledger.Get("bubble/" + binding.ThreadId)!.Value;
        Check(saved.GetProperty("pendingResponses").EnumerateArray().Any(p => p.GetProperty("sendUnknown").GetBoolean()), "Earlier uncertain response is durably retained across rollover");
        var restored = constructor.Invoke(constructor.GetParameters().Length == 1 ? new object[] { binding } : new object[] { binding, native });
        typeof(Router).GetMethod("RestorePendingBubbles", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, new[] { restored, (object)saved });
        Check((bool)sessionType.GetField("Held")!.GetValue(restored)!, "Restoration holds an uncertain earlier response instead of duplicating it");
        return checks;
    }
    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    private sealed class FixtureNative : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true) => throw new Exception("No native calls in bubble boundary tests");
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No native replies in bubble boundary tests");
    }
    private sealed class FixtureBot : IBot
    {
        public int Sends;
        public int BubbleSends, BubbleEdits;
        public bool UnknownSend;
        public Action? BeforeSend;
        public readonly Dictionary<int, string> Messages = new();
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No polling or controls in bubble boundary tests");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        {
            Sends++; var id = 900 + Sends;
            var before = BeforeSend; BeforeSend = null; before?.Invoke();
            if (UnknownSend) throw new TelegramFailure(0);
            Messages[id] = text;
            return Task.FromResult(Json(new { message_id = id }));
        }
        public Task Edit(long chat, int message, string text, CancellationToken stop) { Messages[message] = text; return Task.CompletedTask; }
        public Task<JsonElement> SendBubble(long chat, int topic, string text, CancellationToken stop)
        { BubbleSends++; return Send(chat, topic, text, stop); }
        public Task EditBubble(long chat, int message, string text, CancellationToken stop)
        { BubbleEdits++; return Edit(chat, message, text, stop); }
    }
}
