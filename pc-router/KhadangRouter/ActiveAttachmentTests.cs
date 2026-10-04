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
        foreach (var scenario in new[] { "active", "completed", "completion-race", "new-turn-race", "held", "approval", "invalid" })
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
                if (scenario == "completion-race") Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "existing", status = "completed" } });
                if (scenario == "new-turn-race") Event("turn/started", new { threadId = binding.ThreadId, turn = new { id = "newer" } });
            };
            if (scenario == "held") type.GetField("Held")!.SetValue(session, true);
            try
            {
                await (Task)typeof(Router).GetMethod("ResumeCodex", flags)!.Invoke(router, new[] { session, CancellationToken.None })!;
                if (scenario == "invalid") throw new Exception("Invalid snapshot accepted");
            }
            catch (InvalidDataException) when (scenario == "invalid") { checks++; }
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
        }
        return checks;
    }
    private sealed class Native(RouterPolicy policy, Binding binding, string scenario) : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Action? DuringRead;
        public List<string> Methods = [];
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Methods.Add(method); var args = JsonSerializer.SerializeToElement(parameters);
            if (args.GetProperty("threadId").GetString() != binding.ThreadId) throw new Exception("Wrong attachment thread");
            if (method == "thread/resume") return Task.FromResult(JsonSerializer.SerializeToElement(new {
                cwd = binding.Workspace, approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", sandbox = new { type = policy.NativeSandboxType },
                thread = new { id = binding.ThreadId, status = new { type = "active", activeFlags = scenario == "approval" ? new[] { "waitingOnApproval" } : Array.Empty<string>() } } }));
            if (method == "thread/turns/list")
            {
                if (effect || args.GetProperty("limit").GetInt32() != 1 || args.GetProperty("itemsView").GetString() != "notLoaded") throw new Exception("Unbounded/mutating attachment read");
                DuringRead?.Invoke();
                return Task.FromResult(JsonSerializer.SerializeToElement(new { data = scenario == "invalid" ? Array.Empty<object>() : new object[] { new { id = "existing", status = scenario == "completed" ? "completed" : "inProgress" } } }));
            }
            throw new Exception("Unexpected attachment action");
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No approvals during attachment");
    }
    private sealed class Bot : IBot
    {
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No Telegram calls in attachment fixture");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => throw new Exception("No sends in attachment fixture");
        public Task Edit(long chat, int message, string text, CancellationToken stop) => throw new Exception("No edits in attachment fixture");
    }
}
