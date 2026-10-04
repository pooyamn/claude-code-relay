using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

// Offline authorization and dispatch fixtures only, never forged live updates.
public static class ParticipantTests
{
    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        const long participant = 199200674, otherChat = -1004395661179;
        var policy = template with { ParticipantIds = [participant], AdditionalChats = [new(otherChat)], StateDirectory = root };
        (policy with { StateDirectory = template.StateDirectory }).Validate();
        JsonElement Message(long sender = participant, long? chat = null, int topic = 53, string text = "Check the current source", bool bot = false,
            string? forbidden = null, bool attachment = false)
        {
            var value = new Dictionary<string, object> { ["from"] = new { id = sender, is_bot = bot },
                ["chat"] = new { id = chat ?? policy.ChatId, is_forum = true }, ["message_thread_id"] = topic, ["message_id"] = 7, ["text"] = text };
            if (forbidden != null) value[forbidden] = new { id = participant };
            if (attachment) value["document"] = new { file_id = "offline-document", file_size = 1 };
            return Json(value);
        }
        foreach (var chat in new[] { policy.ChatId, otherChat })
            foreach (var topic in new[] { 1, 18, 53, 427, 816, 2697 })
                Check(policy.ConversationMessage(Message(chat: chat, topic: topic)) && !policy.OwnerMessage(Message(chat: chat, topic: topic)),
                    "Participant can converse in every admitted topic, but is never the owner");
        foreach (var text in new[] { "/approve exact", "/deny exact", "/answer exact 1 yes", "/goal set task", "/goal pause", "/clear", "/cancel",
            "/model opus", "cc model opus", "CC MODEL cx", "/cc@TheKhadangBot model opus", "  /status", "/remote", "/limits" })
        {
            Check(!policy.ConversationMessage(Message(text: text)), "Participant cannot invoke owner controls: " + text);
            Check(policy.ConversationMessage(Message(sender: policy.OwnerId, text: text)), "Owner controls remain authorized: " + text);
        }
        foreach (var invalid in new[] { Message(sender: participant + 1), Message(bot: true), Message(chat: -1009876),
            Message(forbidden: "sender_chat"), Message(forbidden: "forward_origin"), Message(forbidden: "forward_date"), Message(forbidden: "via_bot") })
            Check(!policy.ConversationMessage(invalid), "Unlisted sender, bot, foreign chat and forwarded/proxy identity denied");
        Check(!(policy with { ParticipantIds = null }).ConversationMessage(Message()), "Missing participant policy grants no access");
        Check(policy.ConversationMessage(Message(attachment: true)), "Normal participant attachment remains authorized");
        foreach (var ids in new long[][] { [0], [-1], [participant, participant], [policy.OwnerId], [long.MaxValue], Enumerable.Range(1, 65).Select(x => (long)x).ToArray() })
        {
            try { (policy with { StateDirectory = template.StateDirectory, ParticipantIds = ids }).Validate(); throw new Exception("Unsafe participant policy accepted"); }
            catch (InvalidDataException) { checks++; }
        }
        // Exercise the actual dispatch gate before BOTH native backend handlers.
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        foreach (var backend in new[] { "codex", "claude" })
        {
            using var ledger = new Ledger(Path.Combine(root, "participant-" + backend + ".db"));
            var binding = new Binding(otherChat, 53, "Participant fixture", template.WorkspaceRoot + "\\fixture",
                backend == "claude" ? "7dc840b0-402f-451e-bc79-dadfb706d363" : "participant-codex", Backend: backend);
            ledger.Bind(binding);
            var native = new Native(); var claude = new Claude(binding.ThreadId); var bot = new Bot(); var media = new Media(policy);
            var router = new Router(policy, ledger, bot, native, attachments: media);
            var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
            if (backend == "claude") type.GetField("Claude")!.SetValue(session, claude);
            var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new object[] { binding.Address });
            long updateId = 1;
            async Task Dispatch(JsonElement message)
            {
                var update = Json(new { message }); ledger.Receive(updateId, update.GetRawText()); ledger.Claim(updateId);
                await (Task)typeof(Router).GetMethod("Handle", flags)!.Invoke(router, new object[] { updateId, update, CancellationToken.None })!;
                updateId++;
            }
            foreach (var text in new[] { "cc model opus", "/approve known-nonce", "/goal set forbidden", "/cancel" })
                await Dispatch(Message(chat: otherChat, text: text));
            Check(native.Calls.Count == 0 && claude.Sends == 0 && bot.Sends == 0 && media.Calls == 0 &&
                ledger.Query("SELECT COUNT(*) FROM updates WHERE status='denied'")[0][0] == "4", "Non-owner controls fail before native, Telegram or media action: " + backend);
            await Dispatch(Message(chat: otherChat));
            Check(ledger.Query("SELECT status FROM updates WHERE id=5")[0][0] == "accepted" &&
                (backend == "claude" ? claude.Sends == 1 : native.Calls.SequenceEqual(new[] { "turn/start" })), "Normal participant starts exact bound session: " + backend);
            await Dispatch(Message(chat: otherChat, text: "Also check uncommitted work", attachment: true));
            Check(ledger.Query("SELECT status FROM updates WHERE id=6")[0][0] == "accepted" && media.Calls == 1 &&
                (backend == "claude" ? claude.Sends == 2 : native.Calls.SequenceEqual(new[] { "turn/start", "turn/steer" })), "Participant attachment steers exact active native session without queue: " + backend);
            Check(ledger.Unknown == 0 && ledger.Bindings().Single() == binding, "Participant never changes native binding or owner identity");
        }
        return checks;
    }
    private sealed class Native : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public List<string> Calls = [];
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls.Add(method);
            return Task.FromResult(method switch { "turn/start" => Json(new { turn = new { id = "participant-turn" } }),
                "turn/steer" => Json(new { turnId = "participant-turn" }), _ => throw new Exception("Unexpected participant native control") });
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("Participant cannot approve");
    }
    private sealed class Claude(string session) : IClaudeNative
    {
        public string SessionId => session;
        public uint Pid => 2;
        public bool Connected => true;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public int Sends;
        public Task<JsonElement> Initialize(CancellationToken stop) => throw new Exception("No participant reinitialization");
        public Task<JsonElement> SendNow(string pin, JsonElement content, CancellationToken stop)
        { if (pin != session) throw new Exception("Wrong participant session"); Sends++; return Task.FromResult(Json(new { session_id = session, uuid = Guid.NewGuid().ToString("D") })); }
        public Task<JsonElement> Control(string subtype, object request, CancellationToken stop, bool effect = true) => throw new Exception("Participant cannot invoke Claude controls");
        public Task Answer(string id, object result, CancellationToken stop) => throw new Exception("Participant cannot approve Claude");
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
    private sealed class Media(RouterPolicy policy) : IAttachments
    {
        public int Calls;
        public Task<IReadOnlyList<StagedAttachment>> Stage(JsonElement message, Binding binding, long updateId, CancellationToken stop)
        { if (!policy.ConversationMessage(message) || !policy.TryAddress(message, out var address) || address != binding.Address) throw new Exception("Wrong participant attachment authority"); Calls++; return Task.FromResult<IReadOnlyList<StagedAttachment>>([]); }
    }
    private sealed class Bot : IBot
    {
        public int Sends;
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No participant admin API");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) { Sends++; return Task.FromResult(Json(new { message_id = 900 })); }
        public Task Edit(long chat, int message, string text, CancellationToken stop) => throw new Exception("No participant bubble edit in fixture");
    }
}
