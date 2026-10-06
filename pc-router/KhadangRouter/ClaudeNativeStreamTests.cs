using System.Text.Json;
using System.Text;
using System.Threading.Channels;

namespace KhadangRouter;

public static class ClaudeNativeStreamTests
{
    private const string Session = "ab87c618-029d-40ad-873b-75f390990ebf";
    public static async Task<int> Run(string root)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        foreach (var mode in new[] { "normal", "reject", "disconnect", "mismatched-replay", "changed-replay", "duplicate-json", "invalid-utf8" })
        {
            var path = Path.Combine(root, "claude-stream-" + mode); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "rpc.db"));
            var channel = new FakeChannel(mode);
            await using var claude = new ClaudeNativeStream(channel, ledger, Session);
            int activity = 0;
            claude.Notification += message => { if (message.GetProperty("type").GetString() == "stream_event") activity++; };
            await claude.Initialize(stop.Token);
            Check(channel.Writes.Count == 1 && channel.Writes[0].GetProperty("request").GetProperty("subtype").GetString() == "initialize",
                "Claude uses one native control initialization, not Codex initialize/initialized");
            try { await claude.Initialize(stop.Token); throw new Exception("Claude initialization replayed"); }
            catch (InvalidOperationException) { Check(channel.Writes.Count == 1, "Duplicate Claude initialization writes nothing"); }
            if (mode == "reject")
            {
                try { await claude.Control("set_model", new { model = "opus[1m]" }, stop.Token); throw new Exception("Rejected model accepted"); }
                catch (NativeRejected) { Check(ledger.Unknown == 0 && channel.Writes.Count == 2, "Explicit Claude control rejection is terminal, not unknown/retried"); }
                continue;
            }
            try
            {
                var replay = await claude.SendNow(Session, JsonSerializer.SerializeToElement("Synthetic steer"), stop.Token);
                Check(mode == "normal" && replay.GetProperty("type").GetString() == "user" && ledger.Unknown == 0,
                    "Exact native user replay confirms delivery, not a made-up turn result");
            }
            catch (IOException)
            {
                Check(mode != "normal" && ledger.Unknown == 1 && !claude.Connected, "Bad or ended Claude stream holds submitted input without replay");
                try { await claude.SendNow(Session, JsonSerializer.SerializeToElement("Do not send"), stop.Token); throw new Exception("Disconnected Claude reused"); }
                catch (IOException) { Check(channel.Writes.Count == 2, "Disconnected Claude cannot fall back to another send or session"); }
            }
            var sent = channel.Writes[1];
            Check(sent.GetProperty("priority").GetString() == "now" && sent.GetProperty("session_id").GetString() == Session &&
                sent.GetProperty("origin").GetProperty("kind").GetString() == "human" &&
                Guid.TryParseExact(sent.GetProperty("uuid").GetString(), "D", out _) && !sent.TryGetProperty("method", out _),
                "Every Claude user input is native send-now with exact local pin and one client UUID");
            Check(channel.Writes.Count == 2, "Claude delivery never retries or queues after a failed receipt");
            if (mode == "normal")
            {
                await claude.Control("remote_control", new { enabled = true, name = "Fixture" }, stop.Token);
                Check(channel.Writes[2].GetProperty("request").GetProperty("enabled").GetBoolean() && ledger.Unknown == 0,
                    "Remote Control uses the measured native control envelope");
                Check(activity == 1, "Native tool/partial activity remains available to the rolling bubble");
                var before = channel.Writes.Count;
                foreach (var invalid in new[] { "foreign", "" })
                {
                    try { await claude.SendNow(invalid, JsonSerializer.SerializeToElement("Foreign"), stop.Token); throw new Exception("Foreign pin accepted"); }
                    catch (InvalidDataException) { Check(channel.Writes.Count == before, "Wrong Claude conversation rejected before input write"); }
                }
                try { await claude.Control("set_model", new { subtype = "remote_control" }, stop.Token); throw new Exception("Reserved control field accepted"); }
                catch (InvalidDataException) { Check(channel.Writes.Count == before, "Caller cannot replace Claude control subtype"); }
                try { await claude.SendNow(Session, JsonSerializer.SerializeToElement(new string('x', ClaudeNativeStream.MaximumFrameBytes)), stop.Token); throw new Exception("Huge Claude input sent"); }
                catch (InvalidDataException) { Check(channel.Writes.Count == before && ledger.Unknown == 0, "Oversized Claude input never becomes a native operation"); }
            }
        }
        foreach (var mode in new[] { "answer", "cancel", "reset" })
        {
            var path = Path.Combine(root, "claude-stream-" + mode); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "rpc.db"));
            var channel = new FakeChannel("normal");
            await using var claude = new ClaudeNativeStream(channel, ledger, Session);
            await claude.Initialize(stop.Token);
            var received = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            claude.Notification += message => {
                if (mode == "answer" && message.GetProperty("type").GetString() == "control_request" ||
                    mode == "cancel" && message.GetProperty("type").GetString() == "control_cancel_request" ||
                    mode == "reset" && message.GetProperty("type").GetString() == "conversation_reset") received.TrySetResult();
            };
            if (mode == "reset") channel.Emit(new { type = "conversation_reset", new_conversation_id = Guid.NewGuid().ToString("D") });
            else
            {
                channel.Emit(new { type = "control_request", request_id = "native-question", request = new { subtype = "can_use_tool", tool_name = "AskUserQuestion" } });
                if (mode == "cancel") channel.Emit(new { type = "control_cancel_request", request_id = "native-question" });
            }
            await received.Task.WaitAsync(stop.Token);
            Check(channel.Writes.Count == 1, "Native question/reset notifications never autoapprove or submit a prompt");
            if (mode == "answer")
            {
                await claude.Answer("native-question", new { behavior = "allow", updatedInput = new { answer = "Fixture" } }, stop.Token);
                Check(channel.Writes[1].GetProperty("type").GetString() == "control_response" && ledger.Unknown == 1,
                    "Human answer uses exact native request; lack of response acknowledgement is retained");
                try { await claude.Answer("native-question", new { behavior = "allow" }, stop.Token); throw new Exception("Claude answer repeated"); }
                catch (InvalidOperationException) { Check(channel.Writes.Count == 2, "A Claude request cannot be answered twice"); }
            }
            else if (mode == "cancel")
            {
                try { await claude.Answer("native-question", new { behavior = "allow" }, stop.Token); throw new Exception("Cancelled Claude request answered"); }
                catch (InvalidOperationException) { Check(channel.Writes.Count == 1 && ledger.Unknown == 0, "Cancelled Claude approval never gets a stale answer"); }
            }
            else
            {
                try { await claude.SendNow(Session, JsonSerializer.SerializeToElement("Old pin"), stop.Token); throw new Exception("Superseded Claude session used"); }
                catch (InvalidOperationException) { Check(channel.Writes.Count == 1, "Phone or CLI clear requires exact new binding, not continued old-pin sends"); }
            }
        }
        var pendingPath = Path.Combine(root, "claude-stream-snapshot"); Directory.CreateDirectory(pendingPath);
        using (var ledger = new Ledger(Path.Combine(pendingPath, "rpc.db")))
        {
            var channel = new FakeChannel("snapshot");
            await using var client = new ClaudeNativeStream(channel, ledger, Session);
            var questions = 0;
            var barrier = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            client.Notification += m => {
                if (m.GetProperty("type").GetString() == "control_request") questions++;
                if (m.GetProperty("type").GetString() == "fixture_barrier") barrier.TrySetResult();
            };
            await client.Initialize(stop.Token);
            Check(questions == 1 && channel.Writes.Count == 1, "Initialization re-arms a pending native question without auto-answering");
            channel.Emit(FakeChannel.Question());
            await client.Answer("snapshot-question", new { behavior = "deny", message = "Fixture" }, stop.Token);
            channel.Emit(FakeChannel.Question()); channel.Emit(new { type = "fixture_barrier" });
            await barrier.Task.WaitAsync(stop.Token);
            Check(questions == 1, "Snapshot/live/answered question replay is rendered once and cannot revive an answer");
            try { await client.Answer("snapshot-question", new { behavior = "allow" }, stop.Token); throw new Exception("Replayed question answered"); }
            catch (InvalidOperationException) { Check(channel.Writes.Count == 2 && ledger.Unknown == 1, "Unacknowledged answer remains durable and is not replayed"); }
        }
        foreach (var wrong in new[] { "none", "session", "uuid", "parent", "role", "content" })
        {
            var path = Path.Combine(root, "claude-late-replay-" + wrong); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "rpc.db"));
            var channel = new FakeChannel("deferred");
            await using var client = new ClaudeNativeStream(channel, ledger, Session) { DeliveryTimeout = TimeSpan.FromMilliseconds(50) };
            await client.Initialize(stop.Token);
            var confirmed = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var barrier = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            client.Notification += m => {
                if (m.GetProperty("type").GetString() == "ccrelay_delivery_confirmed") confirmed.TrySetResult();
                if (m.GetProperty("type").GetString() == "fixture_barrier") barrier.TrySetResult();
            };
            ClaudeDeliveryTimeout expired;
            try { await client.SendNow(Session, JsonSerializer.SerializeToElement("Late exact input"), stop.Token); throw new Exception("Missing ACK not held"); }
            catch (ClaudeDeliveryTimeout e) { expired = e; }
            Check(ledger.Unknown == 1 && channel.Writes.Count == 2, "Timeout retains exactly one uncertain native send");
            var echo = new { type = "user", session_id = wrong == "session" ? Guid.NewGuid().ToString("D") : Session,
                uuid = wrong == "uuid" ? Guid.NewGuid().ToString("D") : expired.Uuid,
                parent_tool_use_id = wrong == "parent" ? "sidechain" : null,
                message = new { role = wrong == "role" ? "assistant" : "user", content = wrong == "content" ? "Changed input" : "Late exact input" } };
            if (wrong == "content")
            {
                try { ClaudeDelivery.ConfirmReplay(ledger, Session, JsonSerializer.SerializeToElement(echo)); throw new Exception("Changed receipt accepted"); }
                catch (InvalidDataException) { checks++; }
            }
            else { channel.Emit(echo); channel.Emit(new { type = "fixture_barrier" }); await barrier.Task.WaitAsync(stop.Token); }
            Check(ledger.Unknown == (wrong == "none" ? 0 : 1) && channel.Writes.Count == 2,
                "Only an exact late session/UUID/content/primary-user receipt resolves uncertainty, with no write: " + wrong);
            if (wrong == "none")
            {
                await confirmed.Task.WaitAsync(stop.Token);
                Check(ClaudeDelivery.Confirmed(ledger, expired.Operation, Session, expired.Uuid), "Late acknowledgement is durable after the in-memory waiter was removed");
                var receipt = ledger.Get(ClaudeDelivery.Key(expired.Operation))!.Value.GetRawText();
                ClaudeDelivery.ConfirmReplay(ledger, Session, JsonSerializer.SerializeToElement(echo));
                Check(ledger.Get(ClaudeDelivery.Key(expired.Operation))!.Value.GetRawText() == receipt && channel.Writes.Count == 2,
                    "Duplicate late echo is idempotent, retaining evidence without another native input");
            }
        }
        return checks;
    }
    private sealed class FakeChannel(string mode) : INativeChannel
    {
        private readonly Channel<string?> frames = Channel.CreateUnbounded<string?>();
        public uint Pid => 123;
        public List<JsonElement> Writes = [];
        public static object Question() => new { type = "control_request", request_id = "snapshot-question", request = new { subtype = "can_use_tool", tool_name = "AskUserQuestion" } };
        public void Emit(object value) => frames.Writer.TryWrite(JsonSerializer.Serialize(value));
        public async Task<string?> Read(CancellationToken stop)
        {
            var frame = await frames.Reader.ReadAsync(stop);
            if (frame == "fixture-invalid-utf8") throw new DecoderFallbackException("Synthetic native UTF-8 failure");
            return frame;
        }
        public Task Write(string message, CancellationToken stop)
        {
            using var document = JsonDocument.Parse(message); var value = document.RootElement.Clone(); Writes.Add(value);
            if (value.GetProperty("type").GetString() == "control_request")
            {
                var subtype = value.GetProperty("request").GetProperty("subtype").GetString();
                Emit(new { type = "control_response", response = new {
                    subtype = mode == "reject" && subtype != "initialize" ? "error" : "success",
                    request_id = value.GetProperty("request_id").GetString(), response = new { session_state = "idle", ok = true },
                    pending_permission_requests = mode == "snapshot" && subtype == "initialize" ? new[] { Question() } : Array.Empty<object>(),
                    pending_user_dialog_requests = Array.Empty<object>() } });
            }
            else if (value.GetProperty("type").GetString() == "user")
            {
                if (mode == "deferred") return Task.CompletedTask;
                if (mode == "disconnect") frames.Writer.TryWrite(null);
                else if (mode == "invalid-utf8") frames.Writer.TryWrite("fixture-invalid-utf8");
                else if (mode == "duplicate-json") frames.Writer.TryWrite("{\"type\":\"user\",\"type\":\"user\"}");
                else
                {
                    Emit(new { type = "stream_event", session_id = Session, @event = new { type = "content_block_delta", delta = new { text = "Fixture progress" } } });
                    Emit(new { type = "user", uuid = value.GetProperty("uuid").GetString(), session_id = mode == "mismatched-replay" ? "foreign" : Session,
                        parent_tool_use_id = (string?)null, message = new { role = "user", content = mode == "changed-replay" ? JsonSerializer.SerializeToElement("Changed input") : value.GetProperty("message").GetProperty("content") } });
                }
            }
            return Task.CompletedTask;
        }
        public ValueTask DisposeAsync() { frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }
}
