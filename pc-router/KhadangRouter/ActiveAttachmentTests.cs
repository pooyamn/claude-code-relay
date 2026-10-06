using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

public static class ActiveAttachmentTests
{
    public static async Task<int> Run(string root, RouterPolicy policy)
    {
        int checks = 0;
        void Check(bool condition, string name) { if (!condition) throw new Exception(name); checks++; }
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        foreach (var scenario in new[] { "active", "completed", "completion-race", "new-turn-race", "held", "approval", "invalid",
            "restore", "restore-completed", "restore-race", "restore-resume-race", "restore-mismatch",
            "restore-mismatch-completed", "restore-mismatch-read-race", "restore-mismatch-resume-race",
            "restore-unknown", "restore-approval", "restore-approval-race", "restore-foreign", "restore-message" })
        {
            using var ledger = new Ledger(Path.Combine(root, "active-attach-" + scenario + ".db"));
            var binding = new Binding(policy.ChatId, 42, "Already running", policy.WorkspaceRoot + "\\lg-magic", "active-native");
            var native = new Native(policy, binding, scenario); var router = new Router(policy, ledger, new Bot(), native);
            var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
            var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new object[] { binding.Address });
            var notify = typeof(Router).GetMethod("OnNative", flags)!;
            void Event(string method, object parameters) => notify.Invoke(router, new[] { (object)JsonSerializer.SerializeToElement(new { method, @params = parameters }) });
            native.DuringRead = () => {
                if (scenario is "completion-race" or "restore-race" or "restore-resume-race") Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "existing", status = "completed" } });
                if (scenario is "new-turn-race" or "restore-mismatch-read-race" or "restore-mismatch-resume-race")
                    Event("turn/started", new { threadId = binding.ThreadId, turn = new { id = "newer" } });
                if (scenario == "restore-approval-race") notify.Invoke(router, new[] { (object)JsonSerializer.SerializeToElement(new {
                    id = 17, method = "item/commandExecution/requestApproval", @params = new { threadId = binding.ThreadId, turnId = "existing", command = "fixture approval" } }) });
            };
            if (scenario == "held") type.GetField("Held")!.SetValue(session, true);
            if (scenario == "restore-unknown") { var operation = ledger.Attempt("native/turn/steer", new { threadId = binding.ThreadId }); ledger.Outcome(operation, "unknown"); }
            if (scenario.StartsWith("restore"))
            { type.GetField("RestoreTurn")!.SetValue(session, "existing"); type.GetProperty("Message")!.SetValue(session, 900); }
            try
            {
                await (Task)typeof(Router).GetMethod("ResumeCodex", flags)!.Invoke(router, new[] { session, CancellationToken.None })!;
                if (scenario is "invalid" or "restore-foreign") throw new Exception("Invalid snapshot accepted");
            }
            catch (InvalidDataException) when (scenario == "invalid") { checks++; }
            catch (InvalidOperationException) when (scenario == "restore-foreign") { checks++; }
            Check(native.Methods.All(m => m is "thread/resume" or "thread/turns/list"), "Attachment never starts, steers, interrupts or forks native work: " + scenario);
            var busy = (bool)type.GetField("Busy")!.GetValue(session)!;
            var turn = (string?)type.GetField("Turn")!.GetValue(session);
            if (scenario == "active")
            {
                Check(busy && turn == "existing", "Attach adopts the exact already-running turn for steering");
                Event("item/agentMessage/delta", new { threadId = binding.ThreadId, turnId = "existing", itemId = "response", delta = "ATTACHED-LIVE" });
                Check(ledger.Get("bubble/active-native")!.Value.GetProperty("tail").GetString()!.Contains("ATTACHED-LIVE"), "Existing active-turn deltas enter the same mapped bubble");
                Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "existing", status = "completed" } });
                Check(!(bool)type.GetField("Busy")!.GetValue(session)! && (string?)type.GetField("Status")!.GetValue(session) == "Done", "Observed completion closes the attached existing turn");
            }
            else if (scenario == "new-turn-race") Check(busy && turn == "newer", "Newer observed turn wins over stale attachment snapshot");
            else if (scenario is "completed" or "completion-race") Check(!busy && turn == null, "Completion cannot be resurrected by stale in-progress snapshot: " + scenario);
            else if (scenario is "held" or "approval") Check((bool)type.GetField("Held")!.GetValue(session)! && !busy, "Attachment never clears unknown receipts or pending native approval: " + scenario);
            else if (scenario == "restore") Check(busy && turn == "existing" && (int?)type.GetProperty("Message")!.GetValue(session) == 900, "Restart attaches exact active turn and retains the existing live bubble");
            else if (scenario is "restore-completed" or "restore-race" or "restore-resume-race") Check(!busy && turn == "existing" && (string?)type.GetField("Status")!.GetValue(session) == "Done", "Restart does not resurrect completion during snapshot: " + scenario);
            else if (scenario is "restore-mismatch" or "restore-message")
                Check(!(bool)type.GetField("Held")!.GetValue(session)! && busy && turn == "replacement", "Exact native work advancing offline does not permanently freeze Telegram input");
            else if (scenario == "restore-mismatch-completed")
                Check(!busy && turn == "replacement" && !(bool)type.GetField("Held")!.GetValue(session)!, "Newer completed work permits future input without inventing a final for the old response");
            else if (scenario is "restore-mismatch-read-race" or "restore-mismatch-resume-race")
                Check(busy && turn == "newer" && !(bool)type.GetField("Held")!.GetValue(session)!, "New native start during recovery wins over stale snapshot without a sticky hold: " + scenario);
            else if (scenario == "restore-unknown")
                Check(!busy && turn == null && ledger.Unknown == 1, "Recovery never bypasses or confirms an uncertain native action");
            else if (scenario is "restore-approval" or "restore-approval-race")
                Check((bool)type.GetField("Held")!.GetValue(session)! && turn == "existing", "Advancing work is not authority to bypass a pending native approval");

            if (scenario == "held")
            {
                Event("turn/started", new { threadId = binding.ThreadId, turn = new { id = "app-work" } });
                Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "app-work", status = "completed" } });
                var rendered = (string)typeof(Router).GetMethod("RenderBubble", flags)!.Invoke(router, new[] { session })!;
                Check(rendered.Contains("Held — Telegram input blocked") && !rendered.Contains("\nDone ("), "Native app completion cannot disguise an input hold as a healthy Done footer");
                Check(ledger.Get("bubble/active-native")!.Value.GetProperty("held").GetBoolean() &&
                    ledger.Get("bubble/active-native")!.Value.GetProperty("status").GetString()!.StartsWith("Held"), "Held state and visible held footer remain durable after app activity");
            }
            if (scenario == "restore-message")
            {
                var update = JsonSerializer.SerializeToElement(new { message = new { from = new { id = policy.OwnerId, is_bot = false },
                    chat = new { id = binding.Chat, is_forum = true }, message_thread_id = binding.Topic, message_id = 50, text = "NEW-AFTER-RECOVERY" } });
                ledger.Receive(50, update.GetRawText()); ledger.Claim(50);
                await (Task)typeof(Router).GetMethod("Handle", flags)!.Invoke(router, new object[] { 50L, update, CancellationToken.None })!;
                Check(ledger.Query("SELECT status FROM updates WHERE id=50")[0][0] == "accepted" && native.Steered == 1 && native.SteerTurn == "replacement",
                    "Actual owner message after restart steers the exact current native turn once, not the old turn or a queue");
            }
        }
        return checks;
    }
    private sealed class Native(RouterPolicy policy, Binding binding, string scenario) : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Action? DuringRead;
        public List<string> Methods = [];
        public int Steered; public string? SteerTurn;
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Methods.Add(method); var args = JsonSerializer.SerializeToElement(parameters);
            if (args.GetProperty("threadId").GetString() != binding.ThreadId) throw new Exception("Wrong attachment thread");
            if (method == "thread/resume") {
                if (scenario is "restore-resume-race" or "restore-mismatch-resume-race") DuringRead?.Invoke();
                return Task.FromResult(JsonSerializer.SerializeToElement(new {
                cwd = binding.Workspace, approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", sandbox = new { type = policy.NativeSandboxType },
                thread = new { id = scenario == "restore-foreign" ? "foreign-thread" : binding.ThreadId,
                    status = new { type = "active", activeFlags = scenario is "approval" or "restore-approval" ? new[] { "waitingOnApproval" } : Array.Empty<string>() } } })); }
            if (method == "thread/turns/list")
            {
                if (effect || args.GetProperty("limit").GetInt32() != 1 || args.GetProperty("itemsView").GetString() != "notLoaded") throw new Exception("Unbounded/mutating attachment read");
                DuringRead?.Invoke();
                return Task.FromResult(JsonSerializer.SerializeToElement(new { data = scenario == "invalid" ? Array.Empty<object>() : new object[] { new {
                    id = scenario is "restore-mismatch" or "restore-mismatch-completed" or "restore-message" ? "replacement" : "existing",
                    status = scenario is "completed" or "restore-completed" or "restore-mismatch-completed" ? "completed" : "inProgress" } } }));
            }
            if (method == "turn/steer") { Steered++; SteerTurn = args.GetProperty("expectedTurnId").GetString(); return Task.FromResult(JsonSerializer.SerializeToElement(new { turnId = SteerTurn })); }
            throw new Exception("Unexpected attachment action");
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No approvals during attachment");
    }
    private sealed class Bot : IBot
    {
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) =>
            method == "sendChatAction" ? Task.FromResult(JsonSerializer.SerializeToElement(true)) : throw new Exception("No Telegram calls in attachment fixture");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => throw new Exception("No sends in attachment fixture");
        public Task Edit(long chat, int message, string text, CancellationToken stop) => throw new Exception("No edits in attachment fixture");
    }
}
