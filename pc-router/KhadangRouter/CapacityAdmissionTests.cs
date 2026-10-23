using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

// Inert fixtures: real dispatch/ledger, no model, network or live configuration.
public static class CapacityAdmissionTests
{
    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool yes, string label) { if (!yes) throw new Exception(label); checks++; }
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        foreach (var backend in new[] { "codex", "claude" })
        foreach (var failure in new[] { -1, 429, 0 })
        {
            var folder = Path.Combine(root, "capacity-" + backend + "-" + failure); Directory.CreateDirectory(folder);
            var policy = template with { StateDirectory = folder, MaximumSessions = 1, StartSpacingSeconds = 1 };
            using var ledger = new Ledger(Path.Combine(folder, "router.db"));
            var target = new Binding(policy.ChatId, 42, "Target", policy.WorkspaceRoot + "\\fixture",
                backend == "claude" ? "7dc840b0-402f-451e-bc79-dadfb706d363" : "capacity-target", Backend: backend);
            var neighbor = target with { Topic = 43, ThreadId = "capacity-neighbor", Backend = "codex" };
            ledger.Bind(target); ledger.Bind(neighbor);
            var native = new Native(); var claude = new Claude(target.ThreadId); var bot = new Bot(ledger, failure);
            var router = new Router(policy, ledger, bot, native);
            object Add(Binding binding)
            {
                var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke([binding, native]);
                var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
                sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, [binding.Address]);
                return session;
            }
            var session = Add(target); var other = Add(neighbor);
            if (backend == "claude") type.GetField("Claude")!.SetValue(session, claude);
            type.GetField("Busy")!.SetValue(other, true); type.GetField("Turn")!.SetValue(other, "other-active-turn");
            async Task Dispatch(long id, string text)
            {
                var message = Json(new { message = new { from = new { id = policy.OwnerId, is_bot = false },
                    chat = new { id = policy.ChatId, is_forum = true }, message_thread_id = 42, message_id = id, text } });
                ledger.Receive(id, message.GetRawText()); ledger.Claim(id);
                await (Task)typeof(Router).GetMethod("Handle", flags)!.Invoke(router, [id, message, CancellationToken.None])!;
            }
            await Dispatch(101, "preserve original instruction without queueing");
            Check(ledger.Query("SELECT status FROM updates WHERE id=101")[0][0] == "retained-capacity", "Capacity has its own pre-dispatch classification: " + backend);
            Check(!(bool)type.GetField("Held")!.GetValue(session)! && !(bool)type.GetField("Busy")!.GetValue(session)!, "Capacity refusal never creates a sticky hold or fake busy turn");
            Check(native.Calls == 0 && claude.Sends == 0 && ledger.Query("SELECT id FROM operations WHERE kind LIKE 'native/%' OR kind LIKE 'claude/%'").Count == 0,
                "Full capacity sends no model input or mutation intent");
            Check((bool)type.GetField("Busy")!.GetValue(other)! && (string?)type.GetField("Turn")!.GetValue(other) == "other-active-turn", "Other native work and exact turn are preserved");
            Check(bot.Notices == 1 && bot.LastChat == target.Chat && bot.LastTopic == target.Topic && bot.LastText.Contains("NOT sent") && !bot.LastText.Contains("Attachment"), "Clean capacity notice uses the exact topic, not a misleading attachment error");
            Check(ledger.Get("capacity-retained/101")!.Value.GetProperty("nativeSubmitted").GetBoolean() == false, "Retained original has scoped no-dispatch evidence");
            using (var reopened = new Ledger(Path.Combine(folder, "router.db")))
                Check(reopened.Pending().Count == 0 && !reopened.Claim(101), "Restart never queues or replays capacity-retained input");
            if (failure == 0)
            {
                Check(ledger.InputUnknown(target) == 0 && ledger.InputUnknown(neighbor) == 0 && ledger.Unknown == 1, "Unknown capacity notice is audited without disabling either topic");
                continue;
            }
            bot.Failure = -1;
            await Dispatch(102, "/status");
            Check(ledger.Query("SELECT status FROM updates WHERE id=102")[0][0] == "control" && native.Calls == 0 && claude.Sends == 0, "Owner status remains usable while every slot is occupied");
            type.GetField("Busy")!.SetValue(other, false);
            await Dispatch(103, "new instruction after capacity becomes free");
            Check(ledger.Query("SELECT status FROM updates WHERE id=103")[0][0] == "accepted" && native.Calls + claude.Sends == 1, "Fresh input works after capacity returns; no maintenance hold clear needed");
            Check(ledger.Query("SELECT status FROM updates WHERE id=101")[0][0] == "retained-capacity" && ledger.Unknown == 0, "Original stays retained, not resent alongside the fresh input");
        }
        return checks;
    }
    private sealed class Native : INative
    {
        public uint Pid => 1; public int Calls;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        { if (method != "turn/start") throw new Exception("Unexpected capacity fixture native call"); Calls++; return Task.FromResult(Json(new { turn = new { id = "fresh-capacity-turn" } })); }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No capacity approval");
    }
    private sealed class Claude(string session) : IClaudeNative
    {
        public uint Pid => 2; public string SessionId => session; public bool Connected => true; public int Sends;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> SendNow(string pin, JsonElement content, CancellationToken stop)
        { if (pin != session) throw new Exception("Wrong native session"); Sends++; return Task.FromResult(Json(new { session_id = pin, uuid = Guid.NewGuid().ToString("D") })); }
        public Task<JsonElement> Initialize(CancellationToken stop) => throw new Exception("No capacity initialization");
        public Task<JsonElement> Control(string subtype, object request, CancellationToken stop, bool effect = true) => throw new Exception("No capacity controls");
        public Task Answer(string id, object result, CancellationToken stop) => throw new Exception("No capacity approval");
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
    private sealed class Bot(Ledger ledger, int failure) : IBot
    {
        public int Failure = failure, Notices; public long LastChat; public int LastTopic; public string LastText = "";
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) =>
            method == "sendChatAction" ? Task.FromResult(Json(true)) : throw new Exception("No capacity bot control");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        {
            Notices++; LastChat = chat; LastTopic = topic; LastText = text;
            if (Failure >= 0)
            { var op = ledger.Attempt("telegram/sendMessage", new { chat_id = chat, message_thread_id = topic, text }); ledger.Outcome(op, Failure == 0 ? "unknown" : "rejected"); throw new TelegramFailure(Failure); }
            return Task.FromResult(Json(new { message_id = 900 + Notices }));
        }
        public Task Edit(long chat, int message, string text, CancellationToken stop) => throw new Exception("No capacity fixture edit");
    }
}
