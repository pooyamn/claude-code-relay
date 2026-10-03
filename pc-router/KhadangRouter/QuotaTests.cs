using System.Text.Json;

namespace KhadangRouter;

public static class QuotaTests
{
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private static JsonElement Raw(string value) => JsonDocument.Parse(value).RootElement.Clone();
    private static JsonElement Account(string? id = "fixture-account") => Json(new {
        account = new { type = "chatgpt", email = "PRIVATE-EMAIL", planType = "pro" },
        workspaceRouting = id == null ? null : new { chatgptAccountId = id, backendOrigin = "PRIVATE-ORIGIN" } });
    private static JsonElement Usage => Raw("""
        {"accountId":"fixture-account","ordinaryUsageAllowed":false,
         "rateLimits":{"limitId":"codex","primary":{"usedPercent":17,"windowDurationMins":300,"resetsAt":2000000000},
                       "secondary":{"usedPercent":90,"windowDurationMins":10080,"resetsAt":2000100000}},
         "rateLimitsByLimitId":{
           "codex":{"limitId":"codex","primary":{"usedPercent":17,"windowDurationMins":300,"resetsAt":2000000000},
                    "secondary":{"usedPercent":90,"windowDurationMins":10080,"resetsAt":2000100000}},
           "review":{"limitId":"review","primary":null,"secondary":{"usedPercent":2,"resetsAt":null},
                     "rateLimitReachedType":"workspace_member_usage_limit_reached","spendControlReached":true}},
         "credits":{"balance":"PRIVATE-CREDIT"},"rateLimitUpsell":{"text":"PRIVATE-UPSELL"}}
        """);
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        void Denied(string payload, string name)
        {
            try { NativeQuota.Parse(Raw(payload), NativeQuota.Account(Account()), DateTimeOffset.UtcNow); throw new Exception(name); }
            catch (Exception error) when (error is InvalidDataException or InvalidOperationException or KeyNotFoundException) { checks++; }
        }
        var fingerprint = NativeQuota.Account(Account());
        var observed = NativeQuota.Parse(Usage, fingerprint, DateTimeOffset.UtcNow);
        Check(observed.AccountVerified && observed.AccountFingerprint == fingerprint && fingerprint!.Length == 64, "Account provenance uses hashed native account ID");
        Check(observed.Buckets.Count == 2 && observed.Buckets.Single(b => b.Id == "codex").Secondary!.UsedPercent == 90, "All buckets/windows retained; legacy alias not double-counted");
        Check(observed.OrdinaryUsageAllowed == false && !observed.ReserveEnforced, "Low percentages cannot restore backend permission or promise reserve enforcement");
        Check(observed.Buckets.Single(b => b.Id == "review").Primary == null && observed.Buckets.Last().Secondary!.DurationMinutes == null, "Missing windows/reset metadata remain unknown");
        Check(!Json(observed).GetRawText().Contains("PRIVATE-") && !Json(observed).GetRawText().Contains("fixture-account"), "No email, account ID, credential, origin or upsell persisted");
        Check(!NativeQuota.Parse(Usage, null, DateTimeOffset.UtcNow).AccountVerified, "Absent active account ID cannot bind backend usage");
        var legacy = NativeQuota.Parse(Raw("{\"rateLimits\":{\"primary\":{\"usedPercent\":100}}}"), fingerprint, DateTimeOffset.UtcNow);
        Check(!legacy.AccountVerified && legacy.OrdinaryUsageAllowed == null && legacy.Buckets.Single().Primary!.ResetsAt == null, "Legacy observation never infers account, permission or reset");
        foreach (var type in new[] { "apiKey", "amazonBedrock" })
        {
            try { NativeQuota.Account(Json(new { account = new { type } })); throw new Exception("Paid mode accepted"); }
            catch (InvalidDataException) { checks++; }
        }
        foreach (var used in new[] { "true", "-1", "101", "1.5", "\"17\"" })
            Denied("{\"rateLimits\":{\"primary\":{\"usedPercent\":" + used + "}}}", "Invalid percentage accepted");
        foreach (var metadata in new[] { "\"resetsAt\":true", "\"resetsAt\":-1", "\"resetsAt\":253402300800", "\"windowDurationMins\":0" })
            Denied("{\"rateLimits\":{\"primary\":{\"usedPercent\":1," + metadata + "}}}", "Invalid window metadata accepted");
        foreach (var payload in new[] {
            "{}", "null", "{\"accountId\":\"foreign\",\"rateLimits\":{}}",
            "{\"ordinaryUsageAllowed\":\"true\",\"rateLimits\":{}}",
            "{\"rateLimits\":{\"limitId\":\"codex\"},\"rateLimitsByLimitId\":{\"codex\":{\"limitId\":\"other\"}}}",
            "{\"rateLimits\":{\"limitId\":\"codex\",\"primary\":{\"usedPercent\":1}},\"rateLimitsByLimitId\":{\"codex\":{\"primary\":{\"usedPercent\":2}}}}",
            "{\"rateLimits\":{},\"rateLimitsByLimitId\":{\"codex\":{},\"codex\":{}}}",
            "{\"rateLimits\":{\"limitId\":\"bad\\nlabel\"}}",
            "{\"rateLimits\":{\"spendControlReached\":1}}",
            "{\"rateLimits\":{\"rateLimitReachedType\":\"unknown\"}}"
        }) Denied(payload, "Invalid quota catalog accepted");
        foreach (var scenario in new[] { "normal", "failure", "race", "account-switch" })
        {
            var native = new QuotaNative(scenario); var view = new NativeQuota(); await view.Read(native, CancellationToken.None);
            Check(view.Snapshot.State == (scenario == "normal" ? "observed" : scenario == "race" ? "stale" : "unavailable"), "Native read outcome: " + scenario);
            Check(native.Calls.All(c => !c.Effect && c.Method is "account/read" or "account/rateLimits/read"), "Quota reads never mutate, invoke models, consume credits or refresh credentials");
            if (scenario == "normal")
            {
                Check(view.Render().Contains("90% used") && view.Render().Contains("not allowed") && view.Render().Contains("not yet enforced"), "Usage rendering preserves negative permissions and labels target honestly");
                view.Invalidate(); Check(view.Snapshot.State == "stale" && !view.Snapshot.AccountVerified && !view.Render().Contains("90% used"), "Sparse update invalidates availability instead of merging permission or windows");
            }
        }
        foreach (var scenario in new[] { "normal", "failure", "race", "slow" })
        {
            var path = Path.Combine(root, "quota-" + scenario); Directory.CreateDirectory(path);
            var workspace = OperatingSystem.IsWindows() ? Path.Combine(path, "workspaces") : "C:\\QuotaWorkspaces";
            if (OperatingSystem.IsWindows()) Directory.CreateDirectory(Path.Combine(workspace, "lg-magic"));
            var policy = template with { StateDirectory = path, WorkspaceRoot = workspace, OwnerFullAccess = true };
            using var ledger = new Ledger(Path.Combine(path, "router.db"));
            ledger.Bind(new Binding(policy.ChatId, 42, "LG", workspace + "\\lg-magic", "quota-thread"));
            ledger.Put("bubble/quota-thread", new { tail = "Existing tool history\n", message = 900, sendUnknown = false, held = false, busy = false, status = "Done", elapsedMs = 11000 });
            var native = new QuotaNative(scenario); var bot = new QuotaBot(policy, native);
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            var running = new Router(policy, ledger, bot, native).Run(stop.Token);
            try { await bot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(5)); }
            finally { stop.Cancel(); try { await running; } catch (OperationCanceledException) { } }
            Check(bot.Sends == 0 && bot.Last!.Contains("Existing tool history") && bot.Last.Contains("Working ("), "Limits/status amend one existing active bubble without clearing tool history");
            Check(!ledger.Get("bubble/quota-thread")!.Value.GetProperty("held").GetBoolean() && ledger.Unknown == 0, "Quota read failure never holds owner session or marks an effect uncertain");
            Check(native.Calls.Count(c => c.Method == "account/rateLimits/read") == 1 && native.Calls.All(c => !c.Method.StartsWith("turn/") || scenario == "slow" && c.Method == "turn/interrupt"), "Foreign sender denied; limits never start/interrupt a turn");
            Check(bot.MenuVerified, "Limits native command registered/read back");
            Check(ledger.Get("native/quota")!.Value.GetProperty("State").GetString() == (scenario is "normal" or "slow" ? "observed" : scenario == "race" ? "stale" : "unavailable"), "Account-wide no-thread notification and read result persist: " + scenario);
            if (scenario == "slow") Check(native.Calls.Single(c => c.Method == "turn/interrupt").Effect && bot.Last!.Contains("Interrupt requested"), "Owner interrupt completes while quota read is pending; no session-lock deadlock");
        }
        return checks;
    }
    private sealed class QuotaNative(string scenario) : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification;
        public List<(string Method, bool Effect)> Calls = [];
        public bool Slow => scenario == "slow";
        private readonly TaskCompletionSource interrupted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public void Event(string method, object parameters) => Notification?.Invoke(Json(new { method, @params = parameters }));
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls.Add((method, effect));
            if (method == "thread/resume") return Task.FromResult(Json(new { cwd = Json(parameters).GetProperty("cwd").GetString(), approvalPolicy = "never", approvalsReviewer = "user", sandbox = new { type = "dangerFullAccess" }, thread = new { id = "quota-thread" } }));
            if (method == "thread/goal/get") return Task.FromResult(Json(new { goal = (object?)null }));
            if (method == "account/read") return Task.FromResult(Account(scenario == "account-switch" && Calls.Count(c => c.Method == method) > 1 ? "foreign" : "fixture-account"));
            if (method == "account/rateLimits/read")
            {
                if (scenario == "failure") throw new NativeRejected(method);
                if (scenario == "race") Event("account/rateLimits/updated", new { rateLimits = new { primary = new { usedPercent = 99 } } });
                if (Slow)
                {
                    async Task<JsonElement> Delayed() { await interrupted.Task.WaitAsync(stop); return Usage; }
                    return Delayed();
                }
                return Task.FromResult(Usage);
            }
            if (method == "turn/interrupt" && Slow) { interrupted.TrySetResult(); return Task.FromResult(Json(new { })); }
            throw new Exception("Unexpected quota fixture RPC: " + method);
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No model request in quota fixture");
    }
    private sealed class QuotaBot(RouterPolicy policy, QuotaNative native) : IBot
    {
        private JsonElement menus;
        private int polls;
        public int Sends;
        public string? Last;
        public bool MenuVerified;
        public TaskCompletionSource Completed = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            if (method == "setMyCommands") { menus = Json(parameters).GetProperty("commands").Clone(); return Json(true); }
            if (method == "getMyCommands") { MenuVerified = menus.EnumerateArray().Any(c => c.GetProperty("command").GetString() == "limits"); return menus; }
            if (method != "getUpdates") throw new Exception("Unexpected quota bot API");
            if (++polls == 1)
            {
                native.Event("turn/started", new { threadId = "quota-thread", turn = new { id = "existing-tool-turn" } });
                native.Event("item/agentMessage/delta", new { threadId = "quota-thread", turnId = "existing-tool-turn", itemId = "tool-history", delta = "Existing tool history\n" });
                object Update(int id, long owner, string text) => new { update_id = id, message = new { from = new { id = owner, is_bot = false }, chat = new { id = policy.ChatId, is_forum = true }, message_thread_id = 42, message_id = id, text } };
                return Json(native.Slow ? new[] { Update(100, policy.OwnerId, "/limits"), Update(101, policy.OwnerId + 1, "/limits"), Update(102, policy.OwnerId, "/cancel"), Update(103, policy.OwnerId, "/status") } :
                    new[] { Update(100, policy.OwnerId, "/limits"), Update(101, policy.OwnerId + 1, "/limits"), Update(102, policy.OwnerId, "/status") });
            }
            await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>());
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) { Sends++; throw new Exception("Quota command cannot create another bubble"); }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        {
            if (message != 900) throw new Exception("Quota bubble receipt changed"); Last = text;
            if (text.Contains("not yet enforced") && text.Contains("PC session:")) Completed.TrySetResult();
            return Task.CompletedTask;
        }
    }
}
