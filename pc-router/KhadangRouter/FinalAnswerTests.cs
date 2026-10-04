using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

public static class FinalAnswerTests
{
    public static async Task<int> Run(string root, RouterPolicy policy)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        var parts = FinalAnswerView.Split("# Result\n\n**Done**. [Source](https://example.invalid/source) and `literal <x>`.\n\n```c\nint x = 1;\n```\nNormal prose.");
        var part = parts.Single();
        Check(part.Text.StartsWith("Result\n\nDone.") && !part.Text.Contains("```") && part.Text.EndsWith("Normal prose."), "Final is formatted prose, not a whole-answer code block");
        Check(part.Entities.Count(e => e.type == "pre") == 1 && part.Text.Substring(part.Entities.Single(e => e.type == "pre").offset,
            part.Entities.Single(e => e.type == "pre").length).StartsWith("int x"), "Only actual code has a pre entity");
        Check(part.Entities.Any(e => e.type == "text_link" && e.url == "https://example.invalid/source") && part.Entities.Count(e => e.type == "bold") == 2,
            "Final source link, heading and emphasis are native Telegram entities");
        var parameters = Telegram.AnswerParameters(policy.ChatId, 42, part);
        Check(!parameters.ContainsKey("disable_notification") && !parameters.ContainsKey("parse_mode") && (int)parameters["message_thread_id"] == 42,
            "Final answer notifies in exact topic; explicit entities keep literal HTML safe");
        Check(Telegram.BubbleSendParameters(policy.ChatId, 42, "Working").ContainsKey("disable_notification"), "Progress stays silent");
        var longText = string.Concat(Enumerable.Repeat("🙂 source text\n", 1400));
        var longParts = FinalAnswerView.Split(longText);
        Check(string.Concat(longParts.Select(p => p.Text)) == longText.TrimEnd('\n') && longParts.All(p => p.Text.Length <= 3900), "Full long final is delivered without tail truncation");
        Check(longParts.All(p => !char.IsLowSurrogate(p.Text[0]) && !char.IsHighSurrogate(p.Text[^1])), "Final chunk boundaries preserve surrogate pairs");
        var codeParts = FinalAnswerView.Split("```\n" + new string('x', 9000) + "\n```");
        Check(codeParts.Length == 3 && codeParts.All(p => p.Entities.Single().type == "pre" && p.Entities.Single().length <= p.Text.Length), "Oversized real code block splits into valid code parts");
        var literal = FinalAnswerView.Split("<b>literal</b> token=PRIVATE-CANARY\nBearer PRIVATE-BEARER").Single();
        Check(literal.Text.Contains("<b>literal</b>") && !literal.Text.Contains("PRIVATE-"), "Literal HTML is not executed and known credentials are redacted");
        var bubble = new RollingBubble();
        bubble.Upsert("tool:1", "⏳ Read file.cs"); bubble.Upsert("tool:1", "✓ Read file.cs");
        Check(bubble.Tail == "✓ Read file.cs", "Tool completion updates one row, not a second log line");
        bubble.Upsert("question:1", "Confirm PB15?"); bubble.Upsert("agent:1", new string('x', 9000));
        var rendered = bubble.Render(TimeSpan.FromSeconds(3665), "paused — test");
        Check(rendered.Contains("Confirm PB15?") && rendered.Contains("Working (1h 1m 5s)") && rendered.Length <= 3900, "Pending question and readable elapsed/goal footer survive overflow");
        Check(RollingBubble.LineTail("old\n" + new string('x', 200) + "\nLATEST LINE", 90).StartsWith("…\n"), "Rolling truncation is explicit");

        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var sessionType = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        var binding = new Binding(policy.ChatId, 42, "fixture", policy.WorkspaceRoot + "\\lg-magic", "final-fixture");
        using var ledger = new Ledger(Path.Combine(root, "final-boundaries.db"));
        var bot = new Bot(); var native = new Native(); var router = new Router(policy, ledger, bot, native);
        var session = sessionType.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
        var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
        sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new object[] { binding.Address });
        var notify = typeof(Router).GetMethod("OnNative", flags)!;
        var flush = typeof(Router).GetMethod("FlushBubble", flags)!;
        void Event(string method, object parameters) => notify.Invoke(router, new[] { (object)JsonSerializer.SerializeToElement(new { method, @params = parameters }) });
        Task Flush() => (Task)flush.Invoke(router, new[] { session, CancellationToken.None })!;
        Event("turn/started", new { threadId = binding.ThreadId, turn = new { id = "turn" } });
        Event("item/agentMessage/delta", new { threadId = binding.ThreadId, turnId = "turn", itemId = "answer", delta = "Partial" });
        Event("item/commandExecution/outputDelta", new { threadId = binding.ThreadId, turnId = "turn", itemId = "tool", delta = "PRIVATE-RAW-STDOUT" });
        Event("item/completed", new { threadId = binding.ThreadId, turnId = "turn", item = new { id = "answer", type = "agentMessage", phase = "final_answer", text = "**Authoritative final**" } });
        await Flush();
        Check(bot.Answers.Count == 0, "No final send before authoritative terminal state");
        Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "turn", status = "completed" } });
        await Flush(); await Flush();
        Check(bot.Answers.Count == 1 && bot.Answers[0].Text == "Authoritative final" && bot.Progress.Contains("Done (") && !bot.Progress.Contains("Partial"),
            "Completed item corrects deltas; terminal progress is acknowledged before exactly one separate final");
        Check(!bot.Progress.Contains("PRIVATE-RAW") && bot.Order[^2] == "progress" && bot.Order[^1] == "answer", "Raw stdout excluded; final follows the frozen progress receipt");
        var saved = ledger.Get("bubble/" + binding.ThreadId)!.Value;
        var restored = new ResponseMessage();
        typeof(Router).GetMethod("RestoreAnswer", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, new[] { (object)restored, saved });
        Check(restored.Answer.Delivered && restored.Answer.Parts.Single().Message == 1001, "Restart restores confirmed final ID, not a new send");
        Event("turn/started", new { threadId = binding.ThreadId, turn = new { id = "uncertain" } });
        Event("item/completed", new { threadId = binding.ThreadId, turnId = "uncertain", item = new { id = "unknown-answer", type = "agentMessage", phase = "final_answer", text = "Unknown send" } });
        Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "uncertain", status = "completed" } });
        bot.FailAnswer = true; await Flush(); await Flush();
        var unknown = ledger.Get("bubble/" + binding.ThreadId)!.Value;
        Check(bot.AnswerAttempts == 2 && unknown.GetProperty("held").GetBoolean() && unknown.GetProperty("finalAnswer").GetProperty("Parts")[0].GetProperty("SendUnknown").GetBoolean(),
            "Lost final-send acknowledgement holds durable intent without duplicate replay");
        var claudeBinding = binding with { Topic = 43, ThreadId = "b03fbbe4-56e8-4e65-8f6a-69f95e7ddece", Backend = "claude" };
        var claudeSession = sessionType.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { claudeBinding, native });
        sessionType.GetField("Claude")!.SetValue(claudeSession, new Claude(claudeBinding.ThreadId));
        sessions.GetType().GetProperty("Item")!.SetValue(sessions, claudeSession, new object[] { claudeBinding.Address });
        var onClaude = typeof(Router).GetMethod("OnClaude", flags)!;
        void ClaudeEvent(object frame) => onClaude.Invoke(router, new[] { claudeSession, (object)JsonSerializer.SerializeToElement(frame) });
        Task ClaudeFlush() => (Task)flush.Invoke(router, new[] { claudeSession, CancellationToken.None })!;
        bot.FailAnswer = false;
        ClaudeEvent(new { type = "system", session_id = claudeBinding.ThreadId, subtype = "session_state_changed", state = "running" });
        var tool = new { type = "tool_use", id = "read", name = "Read", input = new { file_path = "board.kicad_pcb" } };
        ClaudeEvent(new { type = "stream_event", session_id = claudeBinding.ThreadId, @event = new { type = "content_block_start", index = 0, content_block = tool } });
        ClaudeEvent(new { type = "assistant", session_id = claudeBinding.ThreadId, uuid = "tool-frame", message = new { content = new[] { tool } } });
        ClaudeEvent(new { type = "user", session_id = claudeBinding.ThreadId, uuid = "tool-result", message = new { content = new[] { new { type = "tool_result", tool_use_id = "read", content = "PRIVATE-TOOL-OUTPUT" } } } });
        ClaudeEvent(new { type = "assistant", session_id = claudeBinding.ThreadId, uuid = "answer-frame", message = new { content = new[] { new { type = "text", text = "Draft" } } } });
        ClaudeEvent(new { type = "result", session_id = claudeBinding.ThreadId, subtype = "success", result = "**Claude final**" });
        await ClaudeFlush();
        Check(bot.Answers.Count == 1 && !bot.Progress.Contains("Done ("), "Claude result alone is not final delivery before native idle");
        Check(bot.Progress.Split("Read board.kicad_pcb").Length == 2 && bot.Progress.Contains("✓ Read") && !bot.Progress.Contains("PRIVATE-TOOL"), "Claude tool start/assistant/result amend one descriptive row without raw output");
        ClaudeEvent(new { type = "system", session_id = claudeBinding.ThreadId, subtype = "session_state_changed", state = "idle" });
        await ClaudeFlush(); await ClaudeFlush();
        Check(bot.Answers.Count == 2 && bot.Answers[^1].Text == "Claude final" && bot.Progress.Contains("Done ("), "Claude authoritative result delivered once, separately, after actual idle");
        return checks;
    }
    private sealed class Claude(string pin) : IClaudeNative
    {
        public uint Pid => 1;
        public string SessionId => pin;
        public bool Connected => true;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Initialize(CancellationToken stop) => throw new Exception("No native initialization");
        public Task<JsonElement> Control(string subtype, object parameters, CancellationToken stop, bool effect = true) => throw new Exception("No controls");
        public Task<JsonElement> SendNow(string expectedSessionId, JsonElement content, CancellationToken stop) => throw new Exception("No inference");
        public Task Answer(string requestId, object answer, CancellationToken stop) => throw new Exception("No answers");
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
    private sealed class Native : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true) => throw new Exception("No inference");
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No native replies");
    }
    private sealed class Bot : IBot
    {
        public string Progress = "";
        public List<AnswerPart> Answers = [];
        public List<string> Order = [];
        public int AnswerAttempts;
        public bool FailAnswer;
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No polling");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        { Progress = text; Order.Add("progress"); return Task.FromResult(JsonSerializer.SerializeToElement(new { message_id = 900 })); }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        { Progress = text; Order.Add("progress"); return Task.CompletedTask; }
        public Task<JsonElement> SendAnswer(long chat, int topic, AnswerPart part, CancellationToken stop)
        {
            AnswerAttempts++;
            if (FailAnswer) throw new TelegramFailure(0);
            Answers.Add(part); Order.Add("answer"); return Task.FromResult(JsonSerializer.SerializeToElement(new { message_id = 1000 + Answers.Count }));
        }
    }
}
