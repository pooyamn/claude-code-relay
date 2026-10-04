using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

public static class ReceiptTypingTests
{
    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string label) { if (!value) throw new Exception(label); checks++; }
        var address = new TopicAddress(template.ChatId, 53);
        var parameters = Telegram.TypingParameters(address.Chat, address.Topic);
        Check((long)parameters["chat_id"] == address.Chat && (int)parameters["message_thread_id"] == 53 &&
            (string)parameters["action"] == "typing" && parameters.Count == 3, "Typing targets the exact forum topic with no message contents");
        Check(!Telegram.TypingParameters(address.Chat, 0).ContainsKey("message_thread_id"), "Non-forum typing omits topic zero");
        try { Telegram.TypingParameters(address.Chat, -1); throw new Exception("accepted"); }
        catch (InvalidDataException) { checks++; }
        var clock = new Clock(); var bot = new Bot(); var pulse = new ReceiptTyping(bot, clock);
        pulse.Observe(address, CancellationToken.None); await pulse.Drain();
        pulse.Observe(address, CancellationToken.None); await pulse.Drain();
        Check(bot.Addresses.SequenceEqual(new[] { address }), "Rapid messages coalesce one short receipt pulse");
        var other = new TopicAddress(-1004395661179, 53);
        pulse.Observe(other, CancellationToken.None); await pulse.Drain();
        Check(bot.Addresses.Last() == other && bot.Addresses.Count == 2, "Same topic number in another forum remains a different destination");
        clock.Now = clock.Now.AddSeconds(3); pulse.Observe(address, CancellationToken.None); await pulse.Drain();
        Check(bot.Addresses.Count == 3 && Json(pulse.Snapshot).GetProperty("confirmed").GetInt64() == 3, "A later incoming message produces a fresh confirmed receipt");
        clock.Now = clock.Now.AddSeconds(4); pulse.Refresh(address, true, CancellationToken.None); await pulse.Drain();
        Check(bot.Addresses.Count == 4, "Active work renews typing without requiring another incoming message");
        clock.Now = clock.Now.AddSeconds(4); pulse.Refresh(address, false, CancellationToken.None); await pulse.Drain();
        Check(bot.Addresses.Count == 4, "Idle work stops renewal rather than an always-on liveness claim");
        Check(!Json(pulse.Snapshot).GetProperty("meaning").GetString()!.Contains("accepted"), "Receipt never claims model acceptance");
        bot.Error = new TelegramFailure(429, 70); clock.Now = clock.Now.AddSeconds(3);
        pulse.Observe(address, CancellationToken.None); await pulse.Drain();
        var calls = bot.Addresses.Count; bot.Error = null;
        clock.Now = clock.Now.AddSeconds(69); pulse.Observe(other, CancellationToken.None); await pulse.Drain();
        Check(bot.Addresses.Count == calls, "Telegram retry_after respected globally, not clamped to a shorter cooldown");
        clock.Now = clock.Now.AddSeconds(1); pulse.Observe(other, CancellationToken.None); await pulse.Drain();
        Check(bot.Addresses.Count == calls + 1, "Cooldown ends only for new input, with no retry timer");
        bot.Error = new HttpRequestException("PRIVATE-CREDENTIAL-URL"); clock.Now = clock.Now.AddSeconds(3);
        pulse.Observe(address, CancellationToken.None); await pulse.Drain();
        Check(Json(pulse.Snapshot).GetProperty("failed").GetInt64() == 2 &&
            !Json(pulse.Snapshot).GetRawText().Contains("PRIVATE"), "Cosmetic failures expose no secret exception and create no replay");
        var blocked = new Bot { Block = true }; var capped = new ReceiptTyping(blocked, clock);
        using (var cancel = new CancellationTokenSource())
        {
            for (int i = 1; i <= 10; i++) capped.Observe(new(address.Chat, i), cancel.Token);
            Check(blocked.Addresses.Count == 8 && Json(capped.Snapshot).GetProperty("inFlight").GetInt32() == 8,
                "Slow typing transport has bounded concurrency and no unbounded work queue");
            cancel.Cancel(); await capped.Drain().WaitAsync(TimeSpan.FromSeconds(3));
            Check(Json(capped.Snapshot).GetProperty("inFlight").GetInt32() == 0, "Shutdown drains even a transport ignoring cancellation");
            capped.Observe(other, cancel.Token);
            Check(blocked.Addresses.Count == 8, "Cancelled bridge lifetime starts no receipt call");
        }
        var bounded = new ReceiptTyping(new Bot { Block = true }, clock);
        bounded.Observe(address, CancellationToken.None);
        await bounded.Drain().WaitAsync(TimeSpan.FromSeconds(3));
        Check(Json(bounded.Snapshot).GetProperty("failed").GetInt64() == 1, "Receipt request has its own two-second deadline without native admission");

        // Real Handle gate, both backends: authorization and receipt BEFORE an
        // occupied native dispatch lock. No forged updates reach a live bot.
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        foreach (var backend in new[] { "codex", "claude" })
        {
            using var ledger = new Ledger(Path.Combine(root, "typing-" + backend + ".db"));
            const long participant = 199200674;
            var policy = template with { StateDirectory = root, ParticipantIds = [participant] };
            var binding = new Binding(template.ChatId, 53, "Receipt fixture", template.WorkspaceRoot + "\\fixture",
                backend == "claude" ? "7dc840b0-402f-451e-bc79-dadfb706d363" : "typing-codex", Backend: backend);
            ledger.Bind(binding); var native = new Native(); var claude = new Claude(binding.ThreadId); var receiptBot = new Bot();
            var router = new Router(policy, ledger, receiptBot, native, attachments: new Media());
            var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
            if (backend == "claude") type.GetField("Claude")!.SetValue(session, claude);
            var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new object[] { binding.Address });
            var dispatch = (SemaphoreSlim)type.GetField("Dispatch")!.GetValue(session)!;
            JsonElement Update(long sender, string text, bool attachment = false) => Json(new { message = new Dictionary<string, object> {
                ["from"] = new { id = sender, is_bot = false }, ["chat"] = new { id = template.ChatId, is_forum = true },
                ["message_thread_id"] = 53, ["message_id"] = 7, ["text"] = text,
                [attachment ? "document" : "fixture"] = new { file_id = "offline-only", file_size = 1 } } });
            Task Handle(long id, JsonElement update)
            {
                ledger.Receive(id, update.GetRawText()); ledger.Claim(id);
                return (Task)typeof(Router).GetMethod("Handle", flags)!.Invoke(router, new object[] { id, update, CancellationToken.None })!;
            }
            await Handle(1, Update(participant + 1, "unlisted"));
            await Handle(2, Update(participant, "/goal set forbidden"));
            Check(receiptBot.Addresses.Count == 0 && native.Calls == 0 && claude.Sends == 0, "Unauthorized input/controls get no typing or native action: " + backend);
            await dispatch.WaitAsync();
            var handling = Handle(3, Update(participant, "Check the attachment", attachment: true));
            Check(receiptBot.Addresses.SequenceEqual(new[] { binding.Address }) && !handling.IsCompleted && native.Calls == 0 && claude.Sends == 0,
                "Authorized attachment receipt arrives before busy native lock or download: " + backend);
            dispatch.Release(); await handling;
            Check(ledger.Query("SELECT status FROM updates WHERE id=3")[0][0] == "accepted" && ledger.Unknown == 0 &&
                (backend == "claude" ? claude.Sends == 1 : native.Calls == 1), "Typing changes no native input or durable acceptance: " + backend);
            await Handle(-1, Update(template.OwnerId, "Synthetic fixture"));
            Check(receiptBot.Addresses.Count == 1, "Synthetic deployment canary has no liveness pulse: " + backend);
            var dispatchPulse = (ReceiptTyping)typeof(Router).GetField("receiptTyping", flags)!.GetValue(router)!;
            await dispatchPulse.Drain();
            receiptBot.Addresses.Clear();
            // Actual native-session state, independent of a slow bubble lock.
            var output = (SemaphoreSlim)type.GetField("Output")!.GetValue(session)!;
            await output.WaitAsync();
            foreach (var status in new[] { "Ready", "Done", "Stopped", "Waiting for owner", "Working" })
            {
                type.GetField("Busy")!.SetValue(session, status == "Working");
                type.GetField("Status")!.SetValue(session, status);
                typeof(Router).GetMethod("RefreshTyping", flags)!.Invoke(router, new object[] { CancellationToken.None });
            }
            // The same topic's receipt may still be coalesced. A second active
            // session proves that output contention cannot stall its heartbeat.
            var secondBinding = binding with { Topic = 54, ThreadId = binding.ThreadId + "-heartbeat" };
            var secondSession = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { secondBinding, native });
            type.GetField("Busy")!.SetValue(secondSession, true); type.GetField("Status")!.SetValue(secondSession, "Working");
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, secondSession, new object[] { secondBinding.Address });
            typeof(Router).GetMethod("RefreshTyping", flags)!.Invoke(router, new object[] { CancellationToken.None }); await dispatchPulse.Drain();
            Check(receiptBot.Addresses.SequenceEqual(new[] { secondBinding.Address }), "Actual heartbeat runs for the working topic despite a locked bubble output: " + backend);
            receiptBot.Addresses.Clear();
            type.GetField("Held")!.SetValue(secondSession, true);
            type.GetField("Busy")!.SetValue(session, false);
            typeof(Router).GetMethod("RefreshTyping", flags)!.Invoke(router, new object[] { CancellationToken.None }); await dispatchPulse.Drain();
            Check(receiptBot.Addresses.Count == 0, "Idle and held actual sessions send no ongoing heartbeat: " + backend);
            output.Release();
            Check(ledger.Query("SELECT COUNT(*) FROM operations WHERE kind='telegram/sendChatAction'")[0][0] == "0",
                "Ephemeral receipt leaves no uncertain durable action: " + backend);
        }
        return checks;
    }
    private sealed class Clock : TimeProvider { public DateTimeOffset Now = DateTimeOffset.UtcNow; public override DateTimeOffset GetUtcNow() => Now; }
    private sealed class Bot : IBot
    {
        public List<TopicAddress> Addresses = []; public Exception? Error; public bool Block;
        public Task<bool> Typing(long chat, int topic, CancellationToken stop)
        { Addresses.Add(new(chat, topic)); if (Error != null) throw Error; return Block ? new TaskCompletionSource<bool>().Task : Task.FromResult(true); }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No admin/network API in receipt fixture");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => Task.FromResult(Json(new { message_id = 900 }));
        public Task Edit(long chat, int message, string text, CancellationToken stop) => Task.CompletedTask;
    }
    private sealed class Native : INative
    {
        public uint Pid => 1; public int Calls; public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        { Calls++; return Task.FromResult(method == "turn/start" ? Json(new { turn = new { id = "typing-turn" } }) : Json(new { turnId = "typing-turn" })); }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No fixture approval");
    }
    private sealed class Claude(string session) : IClaudeNative
    {
        public string SessionId => session; public uint Pid => 2; public bool Connected => true; public int Sends;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Initialize(CancellationToken stop) => throw new Exception("No fixture resume");
        public Task<JsonElement> SendNow(string pin, JsonElement content, CancellationToken stop)
        { if (pin != session) throw new Exception("Wrong session"); Sends++; return Task.FromResult(Json(new { session_id = session, uuid = Guid.NewGuid().ToString("D") })); }
        public Task<JsonElement> Control(string subtype, object request, CancellationToken stop, bool effect = true) => throw new Exception("No fixture control");
        public Task Answer(string id, object result, CancellationToken stop) => throw new Exception("No fixture approval");
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
    private sealed class Media : IAttachments
    {
        public Task<IReadOnlyList<StagedAttachment>> Stage(JsonElement message, Binding binding, long updateId, CancellationToken stop) => Task.FromResult<IReadOnlyList<StagedAttachment>>([]);
    }
}
