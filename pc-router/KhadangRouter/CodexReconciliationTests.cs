using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

internal static class CodexReconciliationTests
{
    internal static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool ok, string name) { if (!ok) throw new Exception(name); checks++; }
        var flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        foreach (var mode in new[] { "idle", "active", "unknown", "malformed-hold", "approval", "foreign", "race", "inconsistent", "output-unknown", "disconnected", "opaque", "empty", "rejected" })
        {
            using var ledger = new Ledger(Path.Combine(root, "reconcile-" + mode + ".db"));
            var binding = new Binding(template.ChatId, 42, "Exact", template.WorkspaceRoot + "\\lg-magic", "exact-reconcile");
            ledger.Bind(binding);
            var native = new Native(binding, mode); var router = new Router(template, ledger, new Bot(), native);
            var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke([binding, native]);
            var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, [binding.Address]);
            type.GetField("Held")!.SetValue(session, true);
            type.GetField("Status")!.SetValue(session, mode == "malformed-hold" ? "Held — malformed native event; inspect this topic" : "Held — reconcile interrupted turn");
            if (mode == "opaque") type.GetField("PreserveSavedBubble")!.SetValue(session, true);
            if (mode == "unknown") { var op = ledger.Attempt("native/turn/start", new { parameters = new { threadId = binding.ThreadId } }); ledger.Outcome(op, "unknown"); }
            if (mode == "output-unknown") { var op = ledger.Attempt("telegram/sendDocument", new { chat_id = binding.Chat, message_thread_id = binding.Topic }); ledger.Outcome(op, "unknown"); }
            native.DuringRead = () => type.GetField("NativeStateRevision")!.SetValue(session, 1L);
            try
            {
                await (Task)typeof(Router).GetMethod(mode == "rejected" ? "ReconcileCodexSafely" : "ReconcileCodex", flags)!.Invoke(router, [session, CancellationToken.None])!;
                Check(mode != "foreign", "Foreign native readback must be refused");
            }
            catch (InvalidDataException) when (mode == "foreign") { checks++; }
            var recovered = mode is "idle" or "active" or "output-unknown" or "empty";
            Check((bool)type.GetField("Held")!.GetValue(session)! != recovered, "Only exact safe stale observations are released: " + mode);
            Check(native.Calls.All(m => m is "thread/read" or "thread/turns/list") && native.Replies == 0,
                "Reconciliation never starts/resumes/steers/interrupts/approves native work: " + mode);
            Check(native.Mutations == 0 && ledger.Pending().Count == 0, "No native mutation or input replay: " + mode);
            if (recovered)
            {
                Check((bool)type.GetField("Busy")!.GetValue(session)! == (mode == "active"), "Current active/idle truth restored: " + mode);
                Check(ledger.Get("native/reconciled/" + binding.ThreadId)!.Value.GetProperty("inputReplay").GetBoolean() == false, "Durable exact non-replay recovery evidence: " + mode);
            }
            if (mode == "rejected") Check(ledger.Get("native/reconcile-fault/" + binding.ThreadId)!.Value.GetProperty("errorType").GetString() == nameof(NativeRejected), "An explicit native refusal stays scoped and cannot kill the shared heartbeat");
            if (mode is "unknown" or "output-unknown") Check(ledger.Unknown == 1, "Original uncertain receipt retained: " + mode);
        }
        foreach (var malformed in new[] { false, true })
        {
            using var ledger = new Ledger(Path.Combine(root, "reconcile-menu-" + malformed + ".db"));
            var binding = new Binding(template.ChatId, 42, "Exact", template.WorkspaceRoot + "\\lg-magic", "exact-menu"); ledger.Bind(binding);
            var menu = malformed ? (object)new { scope = new { type = "chat_member", chat_id = binding.Chat, user_id = template.OwnerId }, commands = Array.Empty<object>(), nativeAction = "not-menu" } :
                new { scope = new { type = "chat_member", chat_id = binding.Chat, user_id = template.OwnerId }, commands = new[] { new { command = "status", description = "Read status" } } };
            var id = ledger.Attempt("telegram/setMyCommands", menu); ledger.Outcome(id, "unknown");
            Check(ledger.InputUnknown(binding) == (malformed ? 1 : 0), "Only structurally exact registered-chat menu uncertainty is non-blocking");
            Check(ledger.Unknown == 1, "Menu timeout remains unknown, not falsely acknowledged");
        }
        foreach (var failure in new[] { "stalled", "failure" })
        {
            var path = Path.Combine(root, "reconcile-menu-run-" + failure); Directory.CreateDirectory(path);
            var policy = template with { StateDirectory = path };
            if (OperatingSystem.IsWindows()) { policy = policy with { WorkspaceRoot = Path.Combine(path, "workspaces") }; Directory.CreateDirectory(Path.Combine(policy.WorkspaceRoot, "lg-magic")); }
            using var ledger = new Ledger(Path.Combine(path, "router.db"));
            var binding = new Binding(policy.ChatId, 42, "Exact", policy.WorkspaceRoot + "\\lg-magic", "exact-menu-run"); ledger.Bind(binding);
            var bot = new Bot(failure); var native = new Native(binding, "startup", policy);
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var running = new Router(policy, ledger, bot, native).Run(stop.Token);
            try
            {
                await bot.MenuStarted.Task.WaitAsync(stop.Token);
                await bot.PollStarted.Task.WaitAsync(TimeSpan.FromSeconds(2), stop.Token);
                Check(!running.IsCompleted, "Slow/failed menu registration cannot block ingress or kill the router: " + failure);
            }
            finally { stop.Cancel(); try { await running; } catch (OperationCanceledException) { } }
        }
        return checks;
    }
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private sealed class Native(Binding binding, string mode, RouterPolicy? policy = null) : INative, INativeConnection
    {
        public uint Pid => 1; public bool Connected => mode != "disconnected"; public string? DisconnectReason => null;
        public List<string> Calls = []; public int Mutations, Replies; public Action? DuringRead;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls.Add(method); if (effect) Mutations++;
            if (mode == "rejected") throw new NativeRejected(method);
            if (method == "thread/resume" && policy != null) return Task.FromResult(Json(new { cwd = binding.Workspace,
                approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", sandbox = new { type = policy.NativeSandboxType },
                thread = new { id = binding.ThreadId, status = new { type = "idle" } } }));
            if (method == "thread/goal/get") return Task.FromResult(Json(new { goal = (object?)null }));
            if (effect) throw new Exception("Reconciliation mutated native state");
            if (method == "thread/read") return Task.FromResult(Json(new { thread = new { id = mode == "foreign" ? "wrong" : binding.ThreadId,
                cwd = binding.Workspace, status = new { type = mode == "active" ? "active" : "idle", activeFlags = mode == "approval" ? new[] { "waitingOnApproval" } : Array.Empty<string>() } } }));
            if (method == "thread/turns/list")
            {
                var args = Json(parameters);
                if (args.GetProperty("limit").GetInt32() != 1 || args.GetProperty("itemsView").GetString() != "notLoaded") throw new Exception("Unbounded reconciliation read");
                if (mode == "race") DuringRead?.Invoke();
                return Task.FromResult(Json(new { data = mode == "empty" ? Array.Empty<object>() : new object[] { new { id = "latest", status = mode is "active" or "inconsistent" ? "inProgress" : "completed" } } }));
            }
            throw new Exception("Unexpected native method");
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) { Replies++; return Task.CompletedTask; }
    }
    private sealed class Bot(string failure = "") : IBot
    {
        public TaskCompletionSource MenuStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource PollStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            if (method == "setMyCommands") { MenuStarted.TrySetResult(); if (failure == "failure") throw new TelegramFailure(0); await Task.Delay(Timeout.Infinite, stop); }
            if (method == "getUpdates") { PollStarted.TrySetResult(); await Task.Delay(Timeout.Infinite, stop); }
            return Json(true);
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => Task.FromResult(Json(new { message_id = 900 }));
        public Task Edit(long chat, int message, string text, CancellationToken stop) => Task.CompletedTask;
    }
}
