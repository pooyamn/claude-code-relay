using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

// No processes, credentials, network, model inference or fabricated live input.
public static class ModelSwitchTests
{
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        foreach (var text in new[] { "cc model opus", "CC MODEL sonnet", "/cc@TheKhadangBot model haiku", "/model cx", "cc model" })
            Check(ModelCommand.TryParse(text, template.BotUsername, out _), "Recognize native legacy model control: " + text);
        foreach (var text in new[] { "say cc model opus", "cc model@other opus", "/cc@other model opus", "/model@other opus", "cc clear" })
            Check(!ModelCommand.TryParse(text, template.BotUsername, out _), "Do not expand unrelated legacy commands: " + text);
        var policy = template with { LinuxWorkspaceRoot = LinuxCodexRuntime.WorkspaceRoot, StateDirectory = root };
        var binding = new Binding(policy.ChatId, 42, "Model fixture", LinuxCodexRuntime.WorkspaceRoot + "/duts", "saved-codex", Runtime: "linux");
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        foreach (var scenario in new[] { "roundtrip", "fresh-codex", "busy", "held", "active-goal", "invalid-model", "handoff-unknown", "wrong-slot" })
        {
            using var ledger = new Ledger(Path.Combine(root, "model-switch-" + scenario + ".db"));
            var source = scenario == "fresh-codex" ? binding with { Backend = "claude", ThreadId = "ae788b3a-c096-4b34-aa27-7cb02009305f" } : binding;
            ledger.Bind(source);
            var bot = new Bot(); var linux = new Native(policy, source.Workspace, scenario); var factory = new Topics { FailSend = scenario == "handoff-unknown" };
            var router = new Router(policy, ledger, bot, new Native(policy, "unused", scenario), claudeTopics: factory, linuxRpc: linux);
            var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { source, linux });
            if (source.Backend == "claude")
            {
                var original = new Claude(source.ThreadId); type.GetField("Claude")!.SetValue(session, original);
                type.GetField("ClaudeInfo")!.SetValue(session, await original.Initialize(CancellationToken.None));
                type.GetField("ClaudeState")!.SetValue(session, "idle");
            }
            type.GetField("LastAnswer")!.SetValue(session, "Verified 51/52 routes; PB15 awaiting confirmation.");
            if (scenario == "busy") type.GetField("Busy")!.SetValue(session, true);
            if (scenario == "held") type.GetField("Held")!.SetValue(session, true);
            var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
            var indexer = sessions.GetType().GetProperty("Item")!;
            indexer.SetValue(sessions, session, new object[] { source.Address });
            // Fixture-only accepted owner request; never reaches a live bot.
            var update = Json(new { message = new { from = new { id = policy.OwnerId, is_bot = false }, chat = new { id = policy.ChatId, is_forum = true },
                message_thread_id = source.Topic, text = "Preserve socket nets; ask me about PB15 before editing." } });
            ledger.Receive(1, update.GetRawText()); ledger.Claim(1); ledger.Finish(1, "accepted");
            if (scenario == "wrong-slot") ledger.Put(ModelCommand.Slot(source.Address, "claude"), source with { Backend = "claude", Topic = 43 });
            async Task Switch(object current, string model) => await (Task)typeof(Router).GetMethod("SwitchModel", flags)!.Invoke(router, new[] { current, model, CancellationToken.None, (object)true })!;
            try
            {
                await Switch(session, source.Backend == "claude" ? "cx" : scenario == "invalid-model" ? "opus\n--continue" : "opus");
                if (scenario is "held" or "wrong-slot" or "handoff-unknown") throw new Exception("Unsafe switch accepted");
            }
            catch (InvalidOperationException) when (scenario == "held") { checks++; }
            catch (InvalidDataException) when (scenario == "wrong-slot") { checks++; }
            catch (IOException) when (scenario == "handoff-unknown") { checks++; }
            if (scenario is "busy" or "held" or "active-goal" or "invalid-model" or "wrong-slot")
            {
                Check(ledger.Bindings().Single() == source && factory.Opened.Count == 0 && linux.Injects.Count == 0, "Rejected control cannot change topic or send a prompt: " + scenario);
                continue;
            }
            if (scenario == "handoff-unknown")
            {
                Check(ledger.Bindings().Single() == source && ledger.Get("model-switch/" + source.Chat + "/" + source.Topic)!.Value.GetProperty("phase").GetString() == "sending-handoff", "Unconfirmed handoff does not replace source binding");
                try { await Switch(session, "opus"); throw new Exception("Unknown handoff replayed"); }
                catch (InvalidOperationException) { checks++; }
                Check(factory.Opened.Count == 1 && factory.Opened[0].Native.Sends.Count == 1, "Incomplete switch is never retried or replaced automatically");
                continue;
            }
            var destination = ledger.Bindings().Single();
            Check(destination.Address == source.Address && destination.Workspace == source.Workspace && destination.Runtime == "linux" && destination.Backend != source.Backend, "Switch preserves exact topic, runtime and worktree");
            var handoff = destination.Backend == "claude" ? factory.Opened.Single().Native.Sends.Single() : linux.Injects.Single();
            Check(handoff.Contains("PB15") && handoff.Contains("Preserve socket nets") && handoff.Contains(" M board.kicad_pcb") && handoff.Contains("No pending approval is transferred"), "Actual destination receives bounded task, answer, dirty worktree and approval handoff");
            Check(ledger.Get(ModelCommand.Slot(source.Address, source.Backend))!.Value.Deserialize<Binding>() == source && ledger.Get(ModelCommand.Slot(source.Address, destination.Backend))!.Value.Deserialize<Binding>() == destination, "Both native IDs are saved separately");
            Check(linux.Calls.All(m => m is not ("turn/start" or "turn/interrupt" or "turn/steer" or "thread/fork")), "Switch never interrupts, forks, or launches a Codex work turn");
            if (scenario == "fresh-codex")
            { Check(linux.Starts == 1 && !linux.Calls.Contains("thread/resume"), "Fresh native Codex ID receives context before any resume attempt"); continue; }
            var claude = factory.Opened.Single().Native;
            var targetSession = indexer.GetValue(sessions, new object[] { source.Address })!;
            claude.Event(new { type = "system", session_id = destination.ThreadId, subtype = "session_state_changed", state = "idle" });
            await Switch(targetSession, "sonnet");
            Check(ledger.Bindings().Single() == destination && factory.Opened.Count == 2 && !factory.Opened[1].Fresh && factory.Opened[1].Model == "sonnet" && claude.Disposes == 1, "Legacy Claude model selection relaunches exact ID, not cached live-only setting");
            factory.Opened[^1].Native.Event(new { type = "system", session_id = destination.ThreadId, subtype = "session_state_changed", state = "idle" });
            targetSession = indexer.GetValue(sessions, new object[] { source.Address })!;
            await Switch(targetSession, "cx");
            Check(ledger.Bindings().Single() == source && linux.Starts == 0 && linux.Injects.Count == 1 && linux.Calls.Contains("thread/resume"), "Return to Codex resumes original saved conversation and injects the return handoff");
        }
        using (var ledger = new Ledger(Path.Combine(root, "model-cas.db")))
        {
            ledger.Bind(binding); var replacement = binding with { ThreadId = "different" };
            try { ledger.ReplaceBinding(binding, replacement, () => throw new IOException()); throw new Exception("CAS failed to rollback"); }
            catch (IOException) { checks++; }
            Check(ledger.Bindings().Single() == binding, "Route and commit receipt rollback together");
            try { ledger.ReplaceBinding(binding with { ThreadId = "stale" }, replacement); throw new Exception("Stale CAS accepted"); }
            catch (InvalidDataException) { checks++; }
            ledger.ReplaceBinding(binding, replacement, () => ledger.Put("committed", true));
            Check(ledger.Bindings().Single() == replacement && ledger.Get("committed")!.Value.GetBoolean(), "Route and switch receipt commit in one SQLite transaction");
        }
        return checks;
    }
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private sealed class Native(RouterPolicy policy, string cwd, string scenario) : INative
    {
        public uint Pid => 2;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public List<string> Calls = [], Injects = [];
        public int Starts;
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls.Add(method); var args = Json(parameters);
            return Task.FromResult(method switch {
                "thread/read" => Json(new { thread = new { id = args.GetProperty("threadId").GetString(), cwd, status = new { type = "idle" } } }),
                "thread/goal/get" => scenario == "active-goal" ? Json(new { goal = new { status = "active" } }) : Json(new { goal = (object?)null }),
                "thread/resume" => Resume(args.GetProperty("threadId").GetString()!),
                "thread/start" => Start(),
                "thread/inject_items" => Inject(args),
                "command/exec" => Json(new { exitCode = 0, stdout = args.GetProperty("command")[1].GetString() == "status" ? " M board.kicad_pcb\n?? unfinished.txt" : "fixture-head/diff" }),
                _ => throw new Exception("Unexpected model-switch RPC " + method)
            });
        }
        private JsonElement Resume(string id) => Json(new { cwd, approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", sandbox = new { type = policy.NativeSandboxType }, thread = new { id } });
        private JsonElement Start() { Starts++; return Resume("fresh-codex"); }
        private JsonElement Inject(JsonElement args) { Injects.Add(args.GetProperty("items")[0].GetProperty("content")[0].GetProperty("text").GetString()!); return Json(new { }); }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No replies");
    }
    private sealed class Topics : IClaudeTopics
    {
        public bool FailSend;
        public List<(Binding Target, bool Fresh, string? Model, Claude Native)> Opened = [];
        public Task<IClaudeNative> Open(Binding binding, CancellationToken stop) => throw new Exception("No startup launch");
        public Task<IClaudeNative> OpenForSwitch(Binding source, Binding target, bool fresh, string? model, CancellationToken stop)
        { var native = new Claude(target.ThreadId) { FailSend = FailSend }; Opened.Add((target, fresh, model, native)); return Task.FromResult<IClaudeNative>(native); }
    }
    private sealed class Claude(string pin) : IClaudeNative
    {
        public uint Pid => 3;
        public string SessionId => pin;
        public bool Connected => Disposes == 0;
        public int Disposes;
        public bool FailSend;
        public List<string> Sends = [];
        public event Action<JsonElement>? Notification;
        public void Event(object frame) => Notification?.Invoke(Json(frame));
        public Task<JsonElement> Initialize(CancellationToken stop) => Task.FromResult(Json(new { session_state = "idle", models = new[] { new { value = "opus" }, new { value = "sonnet" }, new { value = "haiku" } } }));
        public Task<JsonElement> Control(string subtype, object parameters, CancellationToken stop, bool effect = true) => Task.FromResult(subtype == "remote_control" ? Json(new { bridge_session_id = "fixture_bridge", session_url = "https://claude.ai/code/fixture_bridge" }) : Json(new { }));
        public Task<JsonElement> SendNow(string expectedSessionId, JsonElement content, CancellationToken stop)
        { if (expectedSessionId != pin) throw new Exception("Wrong handoff pin"); Sends.Add(content.GetString()!); if (FailSend) throw new IOException("Unconfirmed fixture handoff"); return Task.FromResult(Json(new { session_id = pin })); }
        public Task Answer(string requestId, object answer, CancellationToken stop) => throw new Exception("No approval transfer");
        public ValueTask DisposeAsync() { Disposes++; return ValueTask.CompletedTask; }
    }
    private sealed class Bot : IBot
    {
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No network");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => Task.FromResult(Json(new { message_id = 900 }));
        public Task Edit(long chat, int message, string text, CancellationToken stop) => Task.CompletedTask;
    }
}
