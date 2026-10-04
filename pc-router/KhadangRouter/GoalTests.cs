using System.Text.Json;

namespace KhadangRouter;

public static class GoalTests
{
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private static JsonElement Goal(string status = "active", string objective = "Keep PCB case", string thread = "goal-thread") =>
        Json(new { threadId = thread, objective, status, tokenBudget = 1000, tokensUsed = 37, timeUsedSeconds = 11, createdAt = 1, updatedAt = 2 });
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        foreach (var argument in new[] { "", "status", "STATUS" }) Check(GoalCommand.Parse(argument).Action == "status", "Goal status never becomes an objective");
        Check(GoalCommand.Parse("set\tKeep PCB case") == new GoalCommand("set", "Keep PCB case"), "Explicit set preserves objective case");
        Check(GoalCommand.Parse("Pause").Action == "pause", "Control actions case insensitive");
        foreach (var argument in new[] { "set", new string('x', 4001) })
        { try { GoalCommand.Parse(argument); throw new Exception("Invalid objective accepted"); } catch (InvalidDataException) { checks++; } }
        Check(GoalCommand.Parse(string.Concat(Enumerable.Repeat("🙂", 4000))).Action == "set", "Objective bound counts Unicode scalar characters");
        var view = new NativeGoal("goal-thread"); Check(!view.Known && view.Footer!.Contains("not yet verified"), "Missing native evidence is not no-goal evidence");
        var oldRevision = view.Revision; view.Apply(Goal("paused"));
        Check(!view.Apply(Goal(), oldRevision) && view.Footer!.StartsWith("paused"), "Delayed read cannot replace newer goal event");
        view.Unavailable(oldRevision); Check(view.Known, "Delayed failed read cannot erase a newer observation");
        try { view.Apply(Goal(thread: "foreign")); throw new Exception("Foreign goal accepted"); } catch (InvalidDataException) { checks++; }
        foreach (var field in new[] { "tokensUsed", "timeUsedSeconds", "createdAt", "updatedAt", "tokenBudget" })
        {
            var invalid = JsonSerializer.Deserialize<Dictionary<string, object>>(Goal().GetRawText())!; invalid[field] = true;
            try { view.Apply(Json(invalid)); throw new Exception("Invalid accounting accepted"); } catch (InvalidDataException) { checks++; }
        }
        view.Apply(Goal(objective: "\u202eKeep\npassword='fixture-secret' sk-abcdefghijklmnop " + new string('x', 500)));
        Check(view.Footer!.Length <= 160 && !view.Footer.Contains("fixture-secret") && !view.Footer.Contains("sk-abcdefghijklmnop") && !view.Footer.Any(char.IsControl), "Literal bounded goal footer redacts credentials and control characters");
        view.Apply(Json(null)); Check(view.Known && view.Footer == null, "Native clear removes goal footer");

        foreach (var scenario in new[] { "controls", "complete", "unavailable", "foreign" })
        {
            var path = Path.Combine(root, "goal-" + scenario); Directory.CreateDirectory(path);
            var workspaceRoot = OperatingSystem.IsWindows() ? Path.Combine(path, "workspaces") : "C:\\GoalWorkspaces";
            if (OperatingSystem.IsWindows()) Directory.CreateDirectory(Path.Combine(workspaceRoot, "lg-magic"));
            var policy = template with { StateDirectory = path, WorkspaceRoot = workspaceRoot, OwnerFullAccess = true };
            using var ledger = new Ledger(Path.Combine(path, "goal.db"));
            ledger.Bind(new Binding(policy.ChatId, 42, "Goal fixture", workspaceRoot + "\\lg-magic", "goal-thread"));
            ledger.Put("bubble/goal-thread", new { tail = "Existing work", message = 900, busy = false, held = false, sendUnknown = false, status = "Done", elapsedMs = 4000 });
            var native = new GoalNative(scenario); var bot = new GoalBot(policy, ledger, native, scenario);
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            var run = new Router(policy, ledger, bot, native).Run(stop.Token);
            try { await bot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(10)); }
            finally { stop.Cancel(); try { await run; } catch (OperationCanceledException) { } }
            Check(bot.Sends == 1 && bot.Edits > 0 && bot.Last!.Length <= 3900, "New native turn gets one bubble; goal controls amend that response: " + scenario);
            Check(native.Calls.All(c => !c.Method.StartsWith("turn/") && c.Method != "thread/start"), "Goal controls never fall back to prompts, interrupt tools or create a thread: " + scenario);
            if (scenario == "controls")
            {
                var mutations = native.Calls.Where(c => c.Method is "thread/goal/set" or "thread/goal/clear").ToList();
                Check(mutations.Count == 4 && mutations.All(c => c.Effect), "Four explicit owner mutations, no foreign/bot-targeted replay");
                Check(mutations[0].Parameters.GetProperty("status").GetString() == "paused" && !mutations[0].Parameters.TryGetProperty("objective", out _) && !mutations[0].Parameters.TryGetProperty("tokenBudget", out _), "Pause updates status only");
                Check(mutations[1].Parameters.GetProperty("status").GetString() == "active" && !mutations[1].Parameters.TryGetProperty("objective", out _), "Resume preserves objective/accounting");
                Check(mutations[2].Parameters.GetProperty("objective").GetString() == "Keep PCB case", "Set strips the command keyword");
                Check(bot.PauseState!.Value.GetProperty("busy").GetBoolean() && bot.PauseState.Value.GetProperty("goal").GetProperty("status").GetString() == "paused", "Goal pause does not claim the running turn stopped");
                Check(bot.PauseState.Value.GetProperty("goal").GetProperty("tokensUsed").GetInt64() == 37, "Paused goal accounting survives bubble persistence");
                var last = bot.Last!;
                var footer = last[last.LastIndexOf("\n\nDone (", StringComparison.Ordinal)..];
                Check(!footer.Contains("\nGoal:") && ledger.Get("bubble/goal-thread")!.Value.GetProperty("goal").ValueKind == JsonValueKind.Null, "Clear notification and readback remove current footer without erasing command history");
                Check(!last.Contains("PRIVATE-FOREIGN"), "Foreign goal cannot enter bubble");
                var restartNative = new GoalNative("paused"); var restartBot = new GoalBot(policy, ledger, restartNative, "restart");
                using var restartStop = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                var restarted = new Router(policy, ledger, restartBot, restartNative).Run(restartStop.Token);
                try { await restartBot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(5)); }
                finally { restartStop.Cancel(); try { await restarted; } catch (OperationCanceledException) { } }
                Check(restartBot.Sends == 0 && restartBot.Last!.Contains("\nGoal: paused") && restartNative.Calls.Select(c => c.Method).SequenceEqual(new[] { "thread/resume", "thread/goal/get" }), "Restart reads actual goal on exact thread and preserves bubble without mutation/replay");
            }
            else Check(native.Calls.All(c => c.Method != "thread/goal/set" && c.Method != "thread/goal/clear"), "Missing, completed or foreign goal cannot be resumed: " + scenario);
        }
        return checks;
    }
    private sealed class GoalNative(string scenario) : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification;
        public List<(string Method, JsonElement Parameters, bool Effect)> Calls = [];
        private JsonElement goal = Goal(scenario == "complete" ? "complete" : scenario == "paused" ? "paused" : "active", thread: scenario == "foreign" ? "foreign" : "goal-thread");
        public void Event(string method, object parameters) => Notification?.Invoke(Json(new { method, @params = parameters }));
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            var args = Json(parameters); Calls.Add((method, args, effect));
            if (method == "thread/resume") return Task.FromResult(Json(new { cwd = args.GetProperty("cwd").GetString(), approvalPolicy = "never", approvalsReviewer = "user", sandbox = new { type = "dangerFullAccess" }, thread = new { id = "goal-thread" } }));
            if (method == "thread/goal/get")
            { if (scenario == "unavailable") throw new NativeRejected(method); return Task.FromResult(Json(new { goal })); }
            if (method == "thread/goal/clear")
            { goal = Json(null); Event("thread/goal/cleared", new { threadId = "goal-thread" }); return Task.FromResult(Json(new { })); }
            if (method == "thread/goal/set")
            {
                goal = Goal(args.GetProperty("status").GetString()!, args.TryGetProperty("objective", out var objective) ? objective.GetString()! : goal.GetProperty("objective").GetString()!);
                Event("thread/goal/updated", new { threadId = "foreign", goal = Goal(objective: "PRIVATE-FOREIGN", thread: "foreign") });
                Event("thread/goal/updated", new { threadId = "goal-thread", goal }); return Task.FromResult(Json(new { goal }));
            }
            throw new Exception("Unexpected goal fixture RPC: " + method);
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No model/server request in goal fixture");
    }
    private sealed class GoalBot(RouterPolicy policy, Ledger ledger, GoalNative native, string scenario) : IBot
    {
        public int Sends, Edits;
        public string? Last;
        public JsonElement? PauseState;
        private int polls;
        private JsonElement menus;
        public TaskCompletionSource Completed = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            if (method == "setMyCommands") { menus = Json(parameters).GetProperty("commands").Clone(); return Json(true); }
            if (method == "getMyCommands") return menus;
            if (method != "getUpdates") throw new Exception("Unexpected goal bot API");
            if (scenario == "restart") { await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>()); }
            polls++;
            if (polls == 1) native.Event("turn/started", new { threadId = "goal-thread", turn = new { id = "running-tool-turn" } });
            if (polls == 3) PauseState = ledger.Get("bubble/goal-thread");
            string[] controls = scenario == "controls" ? ["/goal STATUS", "/goal PAUSE", "/goal resume", "/goal SET Keep PCB case", "/goal clear", "/goal resume", "/goal@AnotherBot bad", "/goal foreign-owner"] : ["/goal resume"];
            if (polls <= controls.Length)
            {
                var sender = polls == 8 ? policy.OwnerId + 1 : policy.OwnerId;
                return Json(new[] { new { update_id = 100 + polls, message = new { from = new { id = sender, is_bot = false }, chat = new { id = policy.ChatId, is_forum = true }, message_thread_id = 42, message_id = 100 + polls, text = controls[polls - 1] } } });
            }
            native.Event("turn/completed", new { threadId = "goal-thread", turn = new { id = "running-tool-turn", status = "completed" } });
            await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>());
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        { Sends++; Observe(text); return Task.FromResult(Json(new { message_id = 901 })); }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        {
            if (message is not (900 or 901)) throw new Exception("Unknown goal bubble receipt"); Edits++; Observe(text);
            return Task.CompletedTask;
        }
        private void Observe(string text)
        {
            Last = text;
            if (scenario == "restart" ? text.Contains("\nGoal: paused") : text.Contains("Done (") && text.Contains(scenario == "controls" || scenario == "complete" ? "No resumable goal" : "Goal status unavailable")) Completed.TrySetResult();
        }
    }
}
