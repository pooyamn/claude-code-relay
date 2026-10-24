using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace KhadangRouter;

internal static class ControllerClaudeHandoffTests
{
    internal static async Task<int> Run(string root, RouterPolicy template)
    {
        var checks = 0;
        void Check(bool yes, string text) { if (!yes) throw new Exception(text); checks++; }
        var flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        foreach (var mode in new[] { "idle", "active", "held", "unknown", "capacity", "disconnected", "foreign-state", "pending-request", "requires-action", "state-race", "read-failed", "before-write", "after-write", "rejected", "wrong-session", "wrong-uuid", "wrong-content", "wrong-parent", "timeout" })
        {
            var path = Path.Combine(root, "claude-handoff-" + mode); Directory.CreateDirectory(path);
            var policy = template with { StateDirectory = path }; using var ledger = new Ledger(Path.Combine(path, "router.db"));
            var native = new NoCodex(); var router = new Router(policy, ledger, new Bot(), native);
            var origin = new Binding(policy.ChatId, 18, "Base board", "/Users/pouya/.openclaw/workspace/ai-hil/hardware/augur-1", "11111111-1111-4111-8111-111111111111", "codex", "linux");
            var target = origin with { Topic = 3315, Name = "Mimic", Workspace = "/Users/pouya/.openclaw/workspace/mimic-fast-pcb", ThreadId = "22222222-2222-4222-8222-222222222222", Backend = "claude" };
            var controller = origin with { Topic = 816, ThreadId = "01a0facd-1bc0-7d23-95d6-c32fde0c62db", Workspace = "/Users/pouya/.openclaw/workspace/claude-code-relay" };
            object Add(Binding b)
            {
                ledger.Bind(b); var s = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke([b, native]);
                var map = typeof(Router).GetField("sessions", flags)!.GetValue(router)!; map.GetType().GetProperty("Item")!.SetValue(map, s, [b.Address]); return s;
            }
            var sourceSession = Add(origin); var session = Add(target); var hub = Add(controller);
            var claude = new Claude(target.ThreadId, mode, ledger); type.GetField("Claude")!.SetValue(session, claude);
            type.GetField("ClaudeState")!.SetValue(session, mode == "active" ? "running" : "idle");
            type.GetField("Busy")!.SetValue(session, mode == "active");
            if (mode == "held") type.GetField("Held")!.SetValue(session, true);
            if (mode == "unknown") { var op = ledger.Attempt("claude/user/send-now", new { SessionId = target.ThreadId }); ledger.Outcome(op, "unknown"); }
            if (mode == "state-race") claude.DuringRead = () => type.GetField("ClaudeWorkRevision")!.SetValue(session, 1L);
            if (mode == "capacity") foreach (var s in new[] { sourceSession, hub, Add(origin with { Topic = 42, ThreadId = "other" }) }) type.GetField("Busy")!.SetValue(s, true);
            const string text = "Take responsibility for this approved recovery only; do not replay work.";
            var job = new ControllerHandoff("ccrelay.controller_handoff.v1", "claude-approved-handoff-" + mode, policy.OwnerId, origin, target, text, Hash(text), "Verified native owner message fixture", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow.AddHours(1));
            var reply = await router.DispatchControllerHandoff(job, CancellationToken.None);
            var expected = mode switch { "idle" or "active" => "accepted", "held" or "unknown" => "retained-held", "capacity" => "retained-capacity",
                "disconnected" => "retained-unavailable", "foreign-state" or "pending-request" or "requires-action" or "state-race" => "retained-native-state",
                "read-failed" or "before-write" => "retained-unsubmitted", "rejected" => "rejected", _ => "unknown" };
            Check(reply.GetProperty("state").GetString() == expected, "Claude handoff exact outcome: " + mode);
            var sends = claude.Sends;
            Check(native.Calls == 0 && claude.Controls == 0, "Claude handoff never calls Codex RPCs, controls, approvals or initialization: " + mode);
            Check((bool)type.GetField("Held")!.GetValue(session)! == (mode is "held" or "after-write" or "wrong-session" or "wrong-uuid" or "wrong-content" or "wrong-parent" or "timeout"), "Only uncertain actual native sends create a new hold: " + mode);
            var again = await router.DispatchControllerHandoff(job, CancellationToken.None);
            Check(JsonNode.DeepEquals(JsonNode.Parse(again.GetRawText()), JsonNode.Parse(reply.GetRawText())) && sends == claude.Sends, "Claude accepted/unknown/retained receipt is never replayed: " + mode);
            if (expected == "accepted")
            {
                Check(sends == 1 && reply.GetProperty("mode").GetString() == "now" && reply.GetProperty("turnId").ValueKind == JsonValueKind.Null && Guid.TryParseExact(reply.GetProperty("uuid").GetString(), "D", out _), "Claude uses exact native UUID/priority-now receipt, not an invented Codex turn ID");
                Check(ledger.Unknown == 0 && claude.LastText!.Contains("not a new grant of authority") && claude.LastText.Contains(job.RequestId), "Approved task includes explicit agent provenance and exact original request ID");
            }
            if (mode == "timeout") Check(ledger.Unknown == 1 && reply.GetProperty("operationId").GetString() == claude.LastOperation && reply.GetProperty("uuid").GetString() == Claude.Uuid, "Uncertain handoff retains exact operation/UUID for reconciliation, never a retry");
            if (expected.StartsWith("retained", StringComparison.Ordinal) && mode != "before-write") Check(sends == 0, "Unready/capacity/racing Claude cannot consume an input: " + mode);
            if (mode is "before-write" or "rejected") Check(!(bool)type.GetField("Busy")!.GetValue(session)!, "Proven pre-write/rejected Claude start releases only its reservation");
            if (mode == "idle")
            {
                try { await router.DispatchControllerHandoff(job with { Text = "changed", TextSha256 = Hash("changed") }, CancellationToken.None); throw new Exception("Changed same ID accepted"); }
                catch (InvalidDataException) { Check(claude.Sends == 1, "Changed-content Claude replay is refused before input"); }
            }
        }
        return checks;
    }
    private static string Hash(string text) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private sealed class NoCodex : INative
    {
        public uint Pid => 1; public int Calls;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true) { Calls++; throw new Exception("Codex input on Claude route"); }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No approvals");
    }
    private sealed class Claude(string id, string mode, Ledger ledger) : IClaudeNative, IClaudeStateObservation
    {
        public const string Uuid = "33333333-3333-4333-8333-333333333333";
        public uint Pid => 2; public string SessionId => id; public bool Connected => mode != "disconnected";
        public int Sends, Controls; public string? LastText, LastOperation; public Action? DuringRead;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Initialize(CancellationToken stop) => throw new Exception("No repeated initialization");
        public Task<JsonElement> ReadState(CancellationToken stop)
        {
            if (mode == "read-failed") throw new IOException("Inert read failed"); DuringRead?.Invoke();
            return Task.FromResult(Json(new { session_id = mode == "foreign-state" ? "other" : id,
                session_state = mode == "active" ? "running" : mode == "requires-action" ? "requires_action" : "idle",
                pending_requests = mode == "pending-request" ? new object[] { new { request_id = "approval" } } : Array.Empty<object>() }));
        }
        public Task<JsonElement> SendNow(string expectedSessionId, JsonElement content, CancellationToken stop)
        {
            if (expectedSessionId != id) throw new Exception("Wrong session send");
            if (mode == "before-write") throw new NativeNotSubmitted();
            Sends++; LastText = content.GetString(); LastOperation = ledger.Attempt("claude/user/send-now", new { SessionId = id, uuid = Uuid, content });
            if (mode == "rejected") { ledger.Reject(LastOperation, Json(new { rejected = true })); throw new NativeRejected("claude/send"); }
            if (mode is "after-write" or "timeout")
            { ledger.Outcome(LastOperation, "unknown"); if (mode == "timeout") throw new ClaudeDeliveryTimeout(LastOperation, id, Uuid); throw new IOException("Inert after-write failure"); }
            var echo = Json(new { type = "user", session_id = mode == "wrong-session" ? "other" : id,
                uuid = mode == "wrong-uuid" ? "bad" : Uuid, parent_tool_use_id = mode == "wrong-parent" ? "tool" : (string?)null,
                message = new { role = "user", content = mode == "wrong-content" ? Json("different") : content } });
            if (mode is "idle" or "active") ClaudeDelivery.ConfirmReplay(ledger, id, echo);
            return Task.FromResult(echo);
        }
        public Task<JsonElement> Control(string subtype, object parameters, CancellationToken stop, bool effect = true) { Controls++; throw new Exception("No controls"); }
        public Task Answer(string requestId, object answer, CancellationToken stop) => throw new Exception("No approvals");
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
    private sealed class Bot : IBot
    {
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No Telegram in fixture");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => throw new Exception("No Telegram in fixture");
        public Task Edit(long chat, int message, string text, CancellationToken stop) => throw new Exception("No Telegram in fixture");
    }
}
