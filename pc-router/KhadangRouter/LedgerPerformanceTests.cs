using System.Diagnostics;
using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

internal static class LedgerPerformanceTests
{
    internal static async Task<int> Run(string root, RouterPolicy template)
    {
        var checks = 0;
        void Check(bool ok, string label) { if (!ok) throw new Exception(label); checks++; }
        var path = Path.Combine(root, "receipt-scale.db");
        var bindings = Enumerable.Range(1, 18).Select(i => new Binding(template.ChatId, 100 + i, "Scale " + i,
            template.WorkspaceRoot + "\\lg-magic", $"00000000-0000-0000-0000-{i:000000000000}")).ToArray();
        using (var ledger = new Ledger(path))
        {
            foreach (var binding in bindings) ledger.Bind(binding);
            var payload = JsonSerializer.Serialize(new { text = new string('x', 2048) });
            // Production-sized audit history, without credentials or real text.
            ledger.Transaction(() => ledger.Exec("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<220000) " +
                "INSERT INTO operations SELECT 'history-'||i,'telegram/editMessageText',?,'confirmed',? FROM n", payload, payload));
            var old = new List<string>();
            object Parameters(Binding b) => new { threadId = b.ThreadId, cwd = b.Workspace, excludeTurns = true,
                approvalPolicy = "never", approvalsReviewer = "user", permissions = ":danger-full-access" };
            foreach (var b in bindings.Take(11))
            {
                var id = ledger.Attempt("native/thread/resume", new { id = 1, parameters = Parameters(b) });
                ledger.Outcome(id, "unknown"); old.Add(id);
            }
            var unrelated = new { parameters = Parameters(bindings[^1]) };
            var unrelatedAck = new { thread = new { id = bindings[^1].ThreadId, cwd = bindings[^1].Workspace }, approvalPolicy = "never" };
            ledger.Transaction(() => ledger.Exec("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<4400) " +
                "INSERT INTO operations SELECT 'resume-history-'||i,'native/thread/resume',?,'confirmed',? FROM n",
                JsonSerializer.Serialize(unrelated), JsonSerializer.Serialize(unrelatedAck)));
            foreach (var b in bindings.Take(11))
            {
                var id = ledger.Attempt("native/thread/resume", new { id = 2, parameters = Parameters(b) });
                ledger.Confirm(id, Json(new { thread = new { id = b.ThreadId, cwd = b.Workspace }, approvalPolicy = "never" }));
            }
            var uncertain = ledger.Attempt("native/turn/steer", new { parameters = new { threadId = bindings[4].ThreadId } });
            ledger.Outcome(uncertain, "unknown");
            var output = ledger.Attempt("telegram/sendMessage", new { chat_id = template.ChatId, message_thread_id = bindings[8].Topic });
            ledger.Outcome(output, "unknown");
            var plan = ledger.Query("EXPLAIN QUERY PLAN SELECT id,kind,payload FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'");
            Check(plan.Any(r => r.Any(v => v?.Contains("operations_status_kind", StringComparison.Ordinal) == true)) &&
                !plan.Any(r => r.Any(v => v?.Contains("SCAN operations", StringComparison.Ordinal) == true)), "Admission must seek indexed uncertainty, not scan audit history");
            Check(ledger.Query("EXPLAIN QUERY PLAN SELECT id,payload FROM updates WHERE status='received' ORDER BY id")
                .Any(r => r.Any(v => v?.Contains("updates_status", StringComparison.Ordinal) == true)), "Pending input uses its status index");
            var watch = Stopwatch.StartNew(); var snapshot = ledger.StatusSnapshot(bindings); watch.Stop();
            Console.WriteLine($"Ledger scale fixture: 220000 audit records, 18-topic admission snapshot {watch.Elapsed.TotalMilliseconds:F1} ms.");
            Check(watch.Elapsed < TimeSpan.FromSeconds(2), "18-topic status admission exceeds 2 seconds at 220k-record scale: " + watch.Elapsed);
            Check(snapshot.Admissions[bindings[4].Address].Blocking == 1 && snapshot.Admissions[bindings[8].Address].RetainedOutput == 1,
                "Batched snapshot preserves exact native/output failure domains");
            foreach (var b in bindings) Check(snapshot.Admissions[b.Address] == ledger.Admission(b), "Batched and fresh admission must agree for " + b.Topic);
            Check(snapshot.Unknown == 13 && old.All(id => ledger.Query("SELECT status,result FROM operations WHERE id=?", id)[0]
                .SequenceEqual(new string?[] { "unknown", null })), "Scale optimization never rewrites or falsely confirms unknown history");
            using (var other = new Ledger(path))
            {
                var id = other.Attempt("native/turn/start", new { parameters = new { threadId = bindings[6].ThreadId } }); other.Outcome(id, "unknown");
            }
            Check(ledger.Admission(bindings[6]).Blocking == 1 && ledger.StatusSnapshot(bindings).Admissions[bindings[6].Address].Blocking == 1,
                "New uncertainty from another protected writer is observed without stale cached admission");
            Check(snapshot.Admissions[bindings[6].Address].Blocking == 0, "An already-published diagnostic snapshot is immutable, not dispatch authority");
            ledger.Exec("DROP INDEX operations_status_kind"); ledger.Exec("DROP INDEX updates_status");
        }
        using (var readOnly = Ledger.ReadOnly(path))
            Check(readOnly.Query("SELECT name FROM sqlite_master WHERE type='index' AND name IN ('operations_status_kind','updates_status')").Count == 0,
                "Read-only inspection never migrates or recovers a ledger");
        using (var reopened = new Ledger(path))
        {
            Check(reopened.Query("SELECT name FROM sqlite_master WHERE type='index' AND name IN ('operations_status_kind','updates_status')").Count == 2,
                "Existing installations receive idempotent indexes at owned startup");
            Check(reopened.Unknown == 14 && reopened.Query("SELECT COUNT(*) FROM operations WHERE id LIKE 'history-%'")[0][0] == "220000",
                "Index migration preserves all audit records and uncertainty");
        }
        checks += await StatusIsolation(root, template);
        return checks;
    }
    private static async Task<int> StatusIsolation(string root, RouterPolicy template)
    {
        var checks = 0;
        void Check(bool ok, string label) { if (!ok) throw new Exception(label); checks++; }
        var path = Path.Combine(root, "status-stall"); Directory.CreateDirectory(path);
        var policy = template with { StateDirectory = path, WorkspaceRoot = OperatingSystem.IsWindows() ? Path.Combine(path, "workspaces") : template.WorkspaceRoot };
        if (OperatingSystem.IsWindows()) Directory.CreateDirectory(Path.Combine(policy.WorkspaceRoot, "lg-magic"));
        using var ledger = new Ledger(Path.Combine(path, "router.db"));
        ledger.Bind(new Binding(policy.ChatId, 42, "Existing", policy.WorkspaceRoot + "\\lg-magic", "status-fixture"));
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var native = new Native(policy); var bot = new Bot(policy, entered.Task);
        var router = new Router(policy, ledger, bot, native) {
            BeforeStatusWrite = _ => { entered.TrySetResult(); return release.Task; },
            StatusInterval = TimeSpan.FromMilliseconds(20), HeartbeatInterval = TimeSpan.FromMilliseconds(20) };
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        var running = router.Run(stop.Token);
        try
        {
            await entered.Task.WaitAsync(stop.Token);
            await native.Accepted.Task.WaitAsync(TimeSpan.FromSeconds(1), stop.Token);
            await bot.SecondPoll.Task.WaitAsync(TimeSpan.FromSeconds(1), stop.Token);
            Check(!release.Task.IsCompleted, "Native input and subsequent polling proceed while status publication is stalled");
            Check(native.Starts == 1 && ledger.Query("SELECT status FROM updates WHERE id=1")[0][0] == "accepted", "Slow diagnostics cannot defer or duplicate native input");
            var request = typeof(Router).GetMethod("RequestStatus", BindingFlags.Instance | BindingFlags.NonPublic)!;
            for (int i = 0; i < 1000; i++) request.Invoke(router, null);
            Check(!running.IsCompleted, "Repeated status requests coalesce without overflowing or faulting the observer");
            release.TrySetResult();
            var file = Path.Combine(path, "status.json");
            while (!File.Exists(file)) await Task.Delay(10, stop.Token);
            using var value = JsonDocument.Parse(File.ReadAllText(file));
            Check(value.RootElement.GetProperty("nativeSessions").GetArrayLength() == 1 && value.RootElement.GetProperty("statusBuildMs").GetDouble() >= 0,
                "Published status is a complete atomic snapshot with measured build cost");
        }
        finally
        {
            stop.Cancel(); release.TrySetResult();
            try { await running; } catch (OperationCanceledException) { }
        }
        Check(native.Starts == 1, "Observer shutdown never replays the accepted input");
        return checks;
    }
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private sealed class Native(RouterPolicy policy) : INative, INativeConnection
    {
        public uint Pid => 123; public bool Connected => true; public string? DisconnectReason => null;
        public int Starts; public TaskCompletionSource Accepted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            var p = Json(parameters);
            if (method == "turn/start") { Starts++; Accepted.TrySetResult(); return Task.FromResult(Json(new { turn = new { id = "fixture-turn" } })); }
            return Task.FromResult(method switch {
                "thread/resume" => Json(new { cwd = p.GetProperty("cwd").GetString(), approvalPolicy = policy.NativeApprovalPolicy,
                    approvalsReviewer = "user", sandbox = new { type = policy.NativeSandboxType }, thread = new { id = p.GetProperty("threadId").GetString(), status = new { type = "idle", activeFlags = Array.Empty<string>() } } }),
                "thread/goal/get" => Json(new { goal = (object?)null }),
                _ => throw new Exception("Unexpected performance-fixture native call: " + method) });
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No real approval fixture");
    }
    private sealed class Bot(RouterPolicy policy, Task statusEntered) : IBot
    {
        private int polls; private JsonElement menu;
        public TaskCompletionSource SecondPoll = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            if (method == "getMyCommands") return menu.ValueKind == JsonValueKind.Undefined ? Json(Array.Empty<object>()) : menu;
            if (method == "setMyCommands") { menu = Json(parameters).GetProperty("commands").Clone(); return Json(true); }
            if (method == "sendChatAction") return Json(true);
            if (method != "getUpdates") throw new Exception("Unexpected performance-fixture bot call: " + method);
            if (Interlocked.Increment(ref polls) == 1)
            {
                await statusEntered.WaitAsync(stop); await Task.Delay(30, stop);
                return Json(new[] { new { update_id = 1, message = new { from = new { id = policy.OwnerId, is_bot = false },
                    chat = new { id = policy.ChatId, is_forum = true }, message_thread_id = 42, message_id = 1, text = "One inert test input" } } });
            }
            SecondPoll.TrySetResult(); await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>());
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => Task.FromResult(Json(new { message_id = 900 }));
        public Task Edit(long chat, int message, string text, CancellationToken stop) => Task.CompletedTask;
    }
}
