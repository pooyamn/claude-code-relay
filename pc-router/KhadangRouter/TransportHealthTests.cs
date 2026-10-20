using System.Reflection;
using System.Text.Json;
using System.Threading.Channels;

namespace KhadangRouter;

// Inert failure/recovery fixtures: no provider, Telegram, token or live worker.
public static class TransportHealthTests
{
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        var checks = 0;
        void Check(bool ok, string label) { if (!ok) throw new Exception(label); checks++; }
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        object Add(Router router, Binding binding, INative native)
        {
            var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke([binding, native]);
            var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
            sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, [binding.Address]);
            return session;
        }
        foreach (var stalled in new[] { false, true })
        {
            var path = Path.Combine(root, "health-probe-" + stalled); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "router.db"));
            var wire = new ProbeWire(stalled);
            await using var rpc = new NativeRpc(wire, ledger) { ReplyTimeout = stalled ? TimeSpan.FromMilliseconds(30) : TimeSpan.FromSeconds(2) };
            await rpc.CheckLiveness(CancellationToken.None);
            Check(wire.Writes == 1 && ledger.Query("SELECT id FROM operations").Count == 0, "Liveness probe is a read without a model turn or mutation intent");
            Check(rpc.Connected != stalled, "Open-but-unresponsive transport is detected without a cached-PID false healthy");
            if (!stalled)
            { await rpc.CheckLiveness(CancellationToken.None); Check(wire.Writes == 1 && rpc.LastRoundTripAt != null, "Recent authenticated replies suppress redundant probes"); }
            else Check(ledger.Unknown == 0 && rpc.DisconnectReason == "ReadProbeTimeoutException", "Read probe timeout never invents or confirms a native mutation");
        }
        foreach (var mode in new[] { "idle-unsubmitted", "active-unsubmitted", "unknown-after-write" })
        {
            var path = Path.Combine(root, "health-" + mode); Directory.CreateDirectory(path);
            var policy = template with { StateDirectory = path };
            using var ledger = new Ledger(Path.Combine(path, "router.db"));
            var binding = new Binding(policy.ChatId, 42, "Exact topic", policy.WorkspaceRoot + "\\lg-magic", "health-native");
            ledger.Bind(binding);
            var wire = new Wire();
            await using var rpc = new NativeRpc(wire, ledger);
            if (mode != "unknown-after-write")
            {
                wire.Drop();
                using var wait = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                while (rpc.Connected) await Task.Delay(1, wait.Token);
            }
            var router = new Router(policy, ledger, new Bot(), rpc); var session = Add(router, binding, rpc);
            if (mode != "idle-unsubmitted")
            { type.GetField("Busy")!.SetValue(session, true); type.GetField("Turn")!.SetValue(session, "existing-turn"); }
            var update = Json(new { message = new { from = new { id = policy.OwnerId, is_bot = false }, chat = new { id = policy.ChatId, is_forum = true },
                message_thread_id = 42, message_id = 51, text = "fixture input, never replay" } });
            ledger.Receive(51, update.GetRawText()); ledger.Claim(51);
            await (Task)typeof(Router).GetMethod("Handle", flags)!.Invoke(router, [51L, update, CancellationToken.None])!;
            var saved = ledger.Get("bubble/" + binding.ThreadId)!.Value;
            var status = ledger.Query("SELECT status FROM updates WHERE id=51")[0][0];
            if (mode.EndsWith("unsubmitted", StringComparison.Ordinal))
            {
                Check(status == "retained-unsubmitted" && !saved.GetProperty("held").GetBoolean(), "Proven pre-dispatch failure never creates a sticky hold: " + mode);
                Check(ledger.Unknown == 0 && wire.Writes == 0 && ledger.Query("SELECT id FROM operations").Count == 0, "Unsubmitted input writes neither a native frame nor mutation intent");
                Check(saved.GetProperty("busy").GetBoolean() == (mode == "active-unsubmitted"), "Unsubmitted idle start releases only its UI reservation; existing active work stays active");
                Check(ledger.Get("native/unsubmitted/51")!.Value.GetProperty("Binding").Deserialize<Binding>() == binding, "Retained unsubmitted input has exact scoped recovery evidence");
                using var reopened = new Ledger(Path.Combine(path, "router.db"));
                Check(reopened.Pending().Count == 0 && !reopened.Claim(51), "Restart cannot select or replay retained unsubmitted input");
            }
            else
            {
                Check(status == "held-no-replay" && saved.GetProperty("held").GetBoolean(), "Disconnect after a write remains explicitly held");
                Check(ledger.Unknown == 1 && wire.Writes == 1, "Uncertain native action is not reclassified as unsubmitted, confirmed or retried");
            }
            Check(rpc.DisconnectReason == "EndOfStream", "Native connection retains a bounded non-secret terminal reason");
            var recover = (bool)typeof(Router).GetMethod("CheckNativeConnections", flags)!.Invoke(router, null)!;
            Check(recover == (mode == "idle-unsubmitted"), "Health checks inspect actual connection and preserve active/uncertain owned Windows work");
            typeof(Router).GetMethod("StatusFile", flags)!.Invoke(router, null);
            using var statusFile = JsonDocument.Parse(File.ReadAllText(Path.Combine(path, "status.json")));
            Check(!statusFile.RootElement.GetProperty("nativeConnected").GetBoolean(), "Fresh status exposes broken native transport despite a nonzero PID");
        }
        {
            var path = Path.Combine(root, "health-background-uncertain"); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "router.db"));
            var native = new HealthNative(template); var router = new Router(template with { StateDirectory = path }, ledger, new Bot(), native);
            var binding = new Binding(template.ChatId, 42, "Owned Windows", template.WorkspaceRoot + "\\lg-magic", "owned-unknown");
            Add(router, binding, native);
            var intent = ledger.Attempt("native/fixture", new { parameters = new { threadId = binding.ThreadId } }); ledger.Outcome(intent, "unknown");
            Check(!(bool)typeof(Router).GetMethod("NativeObserverRestartSafe", flags)!.Invoke(router, null)!,
                "Background-task recovery also preserves uncertain owned Windows work while transport is still connected");
        }
        {
            var path = Path.Combine(root, "health-observer-isolation"); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "router.db"));
            var native = new HealthNative(template); var router = new Router(template with { StateDirectory = path }, ledger, new Bot(), native);
            var a = new Binding(template.ChatId, 42, "A", template.WorkspaceRoot + "\\lg-magic", "topic-a");
            var b = a with { Topic = 43, ThreadId = "topic-b" };
            var sa = Add(router, a, native); var sb = Add(router, b, native);
            void Event(object value) => typeof(Router).GetMethod("OnNative", flags)!.Invoke(router, [Json(value)]);
            Event(new { method = "item/completed", @params = new { threadId = a.ThreadId, item = new { } } });
            Check((bool)type.GetField("Held")!.GetValue(sa)! && !(bool)type.GetField("Held")!.GetValue(sb)!, "Malformed topic event fences only that exact route");
            Event(new { method = "item/completed", @params = new { threadId = a.ThreadId, item = new { id = "null-text", type = "agentMessage", text = (string?)null } } });
            Check(native.Connected, "A null native display field cannot terminate the shared reader");
            Event(new { method = "turn/started", @params = new { threadId = b.ThreadId, turn = new { id = "b-turn" } } });
            Check((bool)type.GetField("Busy")!.GetValue(sb)! && native.Connected, "Other topic notifications and shared transport survive a view/schema error");
            Event(new { method = "fixture/global", @params = (object?)null });
            Check(!(bool)type.GetField("Held")!.GetValue(sb)!, "Malformed unscoped diagnostic cannot poison an unrelated topic");
            Event(new { id = 7, method = "item/tool/requestUserInput", @params = new { threadId = a.ThreadId } });
            Check(native.Replies == 0 && native.Calls.Count == 0, "Malformed native approval/question is never answered or converted into work");
            Check(!ledger.Get("native/observer-fault/windows")!.Value.GetRawText().Contains("fixture/global"), "Fault audit contains types and selected scope, not raw model/tool content");
        }
        {
            var path = Path.Combine(root, "health-supervisor-exit"); Directory.CreateDirectory(path);
            var policy = template with { StateDirectory = path,
                WorkspaceRoot = OperatingSystem.IsWindows() ? Path.Combine(path, "workspaces") : template.WorkspaceRoot };
            if (OperatingSystem.IsWindows()) Directory.CreateDirectory(Path.Combine(policy.WorkspaceRoot, "lg-magic"));
            using var ledger = new Ledger(Path.Combine(path, "router.db"));
            ledger.Bind(new Binding(policy.ChatId, 42, "Existing", policy.WorkspaceRoot + "\\lg-magic", "health-native"));
            var native = new HealthNative(policy); var bot = new Bot();
            var router = new Router(policy, ledger, bot, native) { HeartbeatInterval = TimeSpan.FromMilliseconds(10) };
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var running = router.Run(stop.Token);
            if (await Task.WhenAny(running, bot.PollStarted.Task).WaitAsync(stop.Token) == running) await running;
            await bot.PollStarted.Task.WaitAsync(stop.Token); native.Alive = false;
            try { await running.WaitAsync(TimeSpan.FromSeconds(2)); throw new Exception("Disconnected service kept polling"); }
            catch (IOException) { checks++; }
            Check(bot.Polls == 1 && native.Calls.All(m => m is "thread/resume" or "thread/goal/get"), "Dead observer stops for supervised exact-session reattachment without replaying native work");
            Check(ledger.Get("native/connection-lost/windows")!.Value.GetProperty("state").GetString() == "supervised-reattach-no-replay", "Connection-loss audit is durable before supervised exit");
            Check(ledger.Unknown == 0, "Health recovery does not invent an ambiguous native action");
        }
        return checks;
    }
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private sealed class ProbeWire(bool stalled) : INativeChannel
    {
        private readonly Channel<string?> frames = Channel.CreateUnbounded<string?>();
        public int Writes; public uint Pid => 123;
        public async Task<string?> Read(CancellationToken stop) => await frames.Reader.ReadAsync(stop);
        public Task Write(string value, CancellationToken stop)
        {
            Writes++; var request = JsonDocument.Parse(value).RootElement;
            if (request.GetProperty("method").GetString() != "thread/loaded/list") throw new Exception("Probe invoked a mutation");
            if (!stalled) frames.Writer.TryWrite(Json(new { id = request.GetProperty("id").GetInt64(), result = new { data = Array.Empty<string>() } }).GetRawText());
            return Task.CompletedTask;
        }
        public ValueTask DisposeAsync() { frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }
    private sealed class Wire : INativeChannel
    {
        private readonly Channel<string?> frames = Channel.CreateUnbounded<string?>();
        public int Writes; public uint Pid => 123;
        public void Drop() => frames.Writer.TryWrite(null);
        public async Task<string?> Read(CancellationToken stop) => await frames.Reader.ReadAsync(stop);
        public Task Write(string value, CancellationToken stop) { Writes++; Drop(); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }
    private sealed class HealthNative(RouterPolicy policy) : INative, INativeConnection
    {
        public volatile bool Alive = true;
        public bool Connected => Alive; public string? DisconnectReason => Alive ? null : "FixtureClosed";
        public uint Pid => 123; public int Replies; public List<string> Calls = [];
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls.Add(method); var args = Json(parameters);
            return Task.FromResult(method switch {
                "thread/resume" => Json(new { cwd = args.GetProperty("cwd").GetString(), approvalPolicy = policy.NativeApprovalPolicy,
                    approvalsReviewer = "user", sandbox = new { type = policy.NativeSandboxType }, thread = new {
                        id = args.GetProperty("threadId").GetString(), status = new { type = "idle", activeFlags = Array.Empty<string>() } } }),
                "thread/goal/get" => Json(new { goal = (object?)null }),
                _ => throw new Exception("Unexpected health fixture native call") });
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) { Replies++; return Task.CompletedTask; }
    }
    private sealed class Bot : IBot
    {
        private JsonElement menu; public int Polls;
        public TaskCompletionSource PollStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            if (method == "sendChatAction") return Json(true);
            if (method == "setMyCommands") { menu = Json(parameters).GetProperty("commands").Clone(); return Json(true); }
            if (method == "getMyCommands") return menu;
            if (method != "getUpdates") throw new Exception("Unexpected health fixture bot method");
            Polls++; PollStarted.TrySetResult(); await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>());
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => Task.FromResult(Json(new { message_id = 900 }));
        public Task Edit(long chat, int message, string text, CancellationToken stop) => Task.CompletedTask;
    }
}
