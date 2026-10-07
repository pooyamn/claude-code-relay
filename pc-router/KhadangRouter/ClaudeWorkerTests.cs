using System.Text.Json;
using System.Threading.Channels;

namespace KhadangRouter;

public static class ClaudeWorkerTests
{
    public static async Task<int> Run(string root)
    {
        int checks = 0;
        void Check(bool condition, string name) { if (!condition) throw new Exception(name); checks++; }
        var binding = new Binding(-100123, 42, "Idle fixture", "/Users/pouya/.openclaw/workspace/fixture",
            "98b493a3-a1a4-4ef2-b7da-b9bf48ece0fe", "claude", "linux");
        var path = Path.Combine(root, "claude-worker-private.db");
        var privateLedger = new Ledger(path);
        var channel = new NativeChannel(binding.ThreadId);
        var native = new ClaudeNativeStream(channel, privateLedger, binding.ThreadId) { DeliveryTimeout = TimeSpan.FromMilliseconds(100) };
        var worker = new ClaudeWorkerNative(native, binding, privateLedger);
        await using (var broker = NativeBroker.Fixture(worker, worker, privateLedger, worker.Initialize))
        {
            await broker.Ready;
            using var routerLedger = new Ledger(Path.Combine(root, "claude-worker-ui.db"));
            var firstWire = new NativeBrokerWireTests.Connection(broker);
            var first = ClaudeWorkerClient.Fixture(firstWire.Client, routerLedger, binding, broker.Epoch, broker.Pid);
            Check(!first.ReattachedGeneration, "First native worker enrollment cannot claim interrupted-work continuity");
            var info = await first.Initialize(CancellationToken.None);
            var remote = await ClaudeRemoteControl.Enable(first, binding, routerLedger, CancellationToken.None);
            Check(info.GetProperty("session_state").GetString() == "idle" && channel.Initializations == 1 && channel.Registrations == 1,
                "Host initializes/registers Claude once, client reads live cache");
            var registration = routerLedger.Get("claude/remote/" + binding.ThreadId)!.Value.GetRawText();
            await first.DisposeAsync(); await firstWire.DisposeAsync();
            Check(native.Connected && !channel.Disposed && channel.Initializations == 1, "Router EOF does not stop or initialize the native worker");
            channel.Emit(new { type = "system", subtype = "session_state_changed", session_id = binding.ThreadId, state = "running" });
            channel.Emit(new { type = "stream_event", session_id = binding.ThreadId, @event = new { type = "offline-fixture" } });
            for (int i = 0; i < 100 && broker.Position < 2; i++) await Task.Delay(10);
            Check(broker.Position >= 2, "Host journals native events with no UI attached");
            await using var secondWire = new NativeBrokerWireTests.Connection(broker);
            var second = ClaudeWorkerClient.Fixture(secondWire.Client, routerLedger, binding, broker.Epoch, broker.Pid);
            Check(second.ReattachedGeneration, "Exact host/native PID, scope, pipe and epoch prove router-only continuity");
            var observed = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            second.Notification += frame => { if (frame.TryGetProperty("event", out var e) && e.GetProperty("type").GetString() == "offline-fixture") observed.TrySetResult(); };
            var liveInfo = await second.Initialize(CancellationToken.None);
            await observed.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var attachedRemote = await ClaudeRemoteControl.Enable(second, binding, routerLedger, CancellationToken.None);
            Check(liveInfo.GetProperty("session_state").GetString() == "running" && attachedRemote == remote && channel.Registrations == 1 && channel.Initializations == 1,
                "Reattached router sees current work/same cloud ID without native initialize/remote registration");
            Check(routerLedger.Get("claude/remote/" + binding.ThreadId)!.Value.GetRawText() == registration, "Reconnect does not amend the saved remote-registration timestamp");
            var input = await second.SendNow(binding.ThreadId, JsonSerializer.SerializeToElement("One explicit owner message"), CancellationToken.None);
            Check(channel.Users == 1 && input.GetProperty("message").GetProperty("content").GetString() == "One explicit owner message" && routerLedger.Unknown == 0,
                "Explicit input crosses protected host once with exact UUID/content native acknowledgement");
            await second.Control("set_model", new { model = "opus" }, CancellationToken.None);
            Check(channel.Models == 1, "Native model controls remain available only on explicit invocation");
            await second.Control("get_usage", new { skip_behaviors = true }, CancellationToken.None, effect: false);
            Check(channel.Usage == 1, "Subscription status remains a native read, not a model turn");
            channel.SuppressEcho = true;
            try { await second.SendNow(binding.ThreadId, JsonSerializer.SerializeToElement("Late receipt, no replay"), CancellationToken.None); throw new Exception("Missing echo was accepted"); }
            catch (ClaudeDeliveryTimeout) { checks++; }
            Check(routerLedger.Unknown == 1 && broker.Unknown == 1 && channel.Users == 2, "Ambiguous delivery fences both UI and custody, without resubmission");
            channel.SuppressEcho = false; channel.Echo(channel.LastUser);
            for (int i = 0; i < 200 && (routerLedger.Unknown != 0 || broker.Unknown != 0); i++) await Task.Delay(10);
            Check(routerLedger.Unknown == 0 && broker.Unknown == 0 && channel.Users == 2, "Exact late echo clears both delivery journals without replay");
            await second.SendNow(binding.ThreadId, JsonSerializer.SerializeToElement("Next owner message"), CancellationToken.None);
            Check(channel.Users == 3, "New explicit input remains usable after late-receipt reconciliation");
            channel.Emit(new { type = "control_request", request_id = "pending-owner-question", request = new { subtype = "can_use_tool", tool_name = "AskUserQuestion", input = new { } } });
            for (int i = 0; i < 100 && native.PendingRequests().Length == 0; i++) await Task.Delay(10);
            await second.DisposeAsync();
            await secondWire.DisposeAsync();
            await using var thirdWire = new NativeBrokerWireTests.Connection(broker);
            var third = ClaudeWorkerClient.Fixture(thirdWire.Client, routerLedger, binding, broker.Epoch, broker.Pid);
            var question = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            third.Notification += frame => { if (frame.TryGetProperty("request_id", out var id) && id.GetString() == "pending-owner-question") question.TrySetResult(); };
            await third.Initialize(CancellationToken.None); await third.RestoreRequests(CancellationToken.None);
            await question.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Check(native.PendingRequests().Length == 1 && channel.Initializations == 1 && channel.Registrations == 1,
                "Live pending questions restore after the event cursor passed them, without native initialize or auto-answer");
            channel.Emit(new { type = "control_cancel_request", request_id = "pending-owner-question" });
            for (int i = 0; i < 100 && native.PendingRequests().Length != 0; i++) await Task.Delay(10);
            Check(native.PendingRequests().Length == 0, "Canceled native requests are absent from reconnection snapshots");
            channel.Emit(new { type = "system", subtype = "session_state_changed", session_id = binding.ThreadId, state = "idle" });
            for (int i = 0; i < 100; i++)
            {
                var status = await thirdWire.Client.Call(Guid.NewGuid().ToString("N"), "claude/status/read", new { }, CancellationToken.None);
                if (status.GetProperty("session_state").GetString() == "idle") break;
                await Task.Delay(10);
            }
            await third.RetireForSwitch(CancellationToken.None);
            Check(channel.Disposed && worker.Retired, "Only explicit idle model-switch retirement stops the worker");
        }
        using (var readOnly = Ledger.ReadOnly(path))
        {
            Check(readOnly.Query("SELECT COUNT(*) FROM broker_events").Count == 1, "Separate component may inspect registry without opening a writer");
            try { readOnly.Put("forbidden", new { }); throw new Exception("Read-only ledger mutated"); }
            catch (UnauthorizedAccessException) { checks++; }
        }
        return checks;
    }
    private sealed class NativeChannel(string session) : INativeChannel
    {
        private readonly Channel<string> frames = Channel.CreateUnbounded<string>();
        public int Initializations, Registrations, Users, Models, Usage;
        public bool Disposed;
        public bool SuppressEcho;
        public JsonElement LastUser;
        public uint Pid => 51;
        public void Emit(object value) => frames.Writer.TryWrite(JsonSerializer.Serialize(value));
        public async Task<string?> Read(CancellationToken stop)
        { try { return await frames.Reader.ReadAsync(stop); } catch (ChannelClosedException) { return null; } }
        public Task Write(string message, CancellationToken stop)
        {
            using var document = JsonDocument.Parse(message); var value = document.RootElement;
            var kind = value.GetProperty("type").GetString();
            if (kind == "control_request")
            {
                var subtype = value.GetProperty("request").GetProperty("subtype").GetString();
                if (subtype == "initialize") Initializations++;
                if (subtype == "remote_control") Registrations++;
                if (subtype == "set_model") Models++;
                if (subtype == "get_usage") Usage++;
                Emit(new { type = "control_response", response = new { subtype = "success", request_id = value.GetProperty("request_id").GetString(),
                    response = new { session_state = "idle", models = Array.Empty<object>(), bridge_session_id = "worker_fixture", session_url = "https://claude.ai/code/worker_fixture" } } });
            }
            else if (kind == "user")
            {
                Users++; LastUser = value.Clone();
                if (!SuppressEcho) Echo(value);
            }
            return Task.CompletedTask;
        }
        public void Echo(JsonElement value) => Emit(new { type = "user", session_id = session, uuid = value.GetProperty("uuid").GetString(), parent_tool_use_id = (string?)null,
            message = new { role = "user", content = value.GetProperty("message").GetProperty("content").Clone() } });
        public ValueTask DisposeAsync() { Disposed = true; frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }
}
