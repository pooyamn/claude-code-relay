using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

public static class ControllerHandoffTests
{
    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    private static string Hash(string value) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        var checks = 0;
        void Check(bool yes, string message) { if (!yes) throw new Exception(message); checks++; }
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        foreach (var mode in new[] { "idle", "active", "held", "uncertain", "capacity", "read-failure", "before-write", "after-write", "rejected", "wrong-ack" })
        {
            var path = Path.Combine(root, "handoff-" + mode); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "router.db"));
            var native = new Native(mode); var policy = template with { StateDirectory = path };
            var router = new Router(policy, ledger, new Bot(), native);
            var source = new Binding(policy.ChatId, 1876, "Origin", "/Users/pouya/.openclaw/workspace/ai-hil", "2c0bce31-f586-4d5e-9422-4be550763ed8", "claude", "linux");
            var target = new Binding(policy.ChatId, 8660, "Web", "/Users/pouya/.openclaw/workspace/ai-hil/web", "01a104a6-9fce-74a3-bdb0-e6dc04237ce7", Runtime: "linux");
            var controller = target with { Topic = 816, ThreadId = "01a0facd-1bc0-7d23-95d6-c32fde0c62db", Workspace = "/Users/pouya/.openclaw/workspace/claude-code-relay" };
            object Add(Binding binding)
            {
                ledger.Bind(binding);
                var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke([binding, native]);
                var map = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
                map.GetType().GetProperty("Item")!.SetValue(map, session, [binding.Address]); return session;
            }
            var origin = Add(source); var session = Add(target); var hub = Add(controller);
            if (mode is "active" or "wrong-ack") { type.GetField("Busy")!.SetValue(session, true); type.GetField("Turn")!.SetValue(session, "active-turn"); }
            if (mode == "held") type.GetField("Held")!.SetValue(session, true);
            if (mode == "uncertain") { var op = ledger.Attempt("native/fixture", new { threadId = target.ThreadId }); ledger.Outcome(op, "unknown"); }
            if (mode == "capacity")
            { type.GetField("Busy")!.SetValue(origin, true); type.GetField("Busy")!.SetValue(hub, true); type.GetField("Busy")!.SetValue(Add(target with { Topic = 43, ThreadId = "other" }), true); }
            var job = new ControllerHandoff("ccrelay.controller_handoff.v1", "approved-handoff-" + mode, policy.OwnerId,
                source, target, "Only the approved scoped task; no old external actions", Hash("Only the approved scoped task; no old external actions"),
                "Verified owner request fixture", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow.AddHours(1));
            var result = await router.DispatchControllerHandoff(job, CancellationToken.None);
            var expected = mode switch { "idle" or "active" => "accepted", "held" or "uncertain" => "retained-held",
                "capacity" => "retained-capacity", "read-failure" or "before-write" => "retained-unsubmitted", "rejected" => "rejected", _ => "unknown" };
            Check(result.GetProperty("state").GetString() == expected, "Exact handoff outcome: " + mode);
            var writes = mode is "idle" or "active" or "after-write" or "rejected" or "wrong-ack" ? 1 : 0;
            Check(native.Writes == writes, "Only admitted native mutation happens, without a retry: " + mode);
            var again = await router.DispatchControllerHandoff(job, CancellationToken.None);
            Check(again.GetProperty("fingerprint").GetString() == result.GetProperty("fingerprint").GetString() && again.GetProperty("state").GetString() == expected && native.Writes == writes, "Accepted, retained and uncertain receipts all deduplicate: " + mode);
            Check((bool)type.GetField("Held")!.GetValue(session)! == (mode is "held" or "after-write" or "wrong-ack"), "Only original/uncertain native work creates a hold: " + mode);
            if (mode == "active") Check(native.LastMethod == "turn/steer" && native.ExpectedTurn == "active-turn", "Active work uses exact-turn steering, not a queued/new turn");
            if (mode is "before-write" or "rejected") Check(!(bool)type.GetField("Busy")!.GetValue(session)!, "Unsubmitted/rejected start rolls back only its UI reservation");
            if (mode != "idle") continue;
            foreach (var bad in new[] { job with { RequestId = "bad-hash", TextSha256 = new string('0', 64) },
                job with { RequestId = "bad-owner", OwnerId = policy.OwnerId + 1 }, job with { RequestId = "bad-expiry", ExpiresAt = DateTimeOffset.UtcNow.AddSeconds(-1) },
                job with { RequestId = "bad-approval", Approval = "" }, job with { RequestId = "bad-source", Source = source with { Topic = 19 } },
                job with { RequestId = "bad-target", Target = target with { Workspace = target.Workspace + "/foreign" } }, job with { Text = "changed", TextSha256 = Hash("changed") } })
            {
                try { await router.DispatchControllerHandoff(bad, CancellationToken.None); throw new Exception("Invalid/changed handoff accepted"); }
                catch (InvalidDataException) { Check(native.Writes == 1, "Bad owner/hash/expiry/binding/changed-ID fails before native mutation"); }
            }
            // Simulated interrupted attempt persists across a fresh router and
            // is NOT converted back into an actionable request.
            var interrupted = job with { RequestId = "interrupted-handoff" };
            var fp = Hash(JsonSerializer.Serialize(interrupted));
            ledger.Put("controller-handoff/" + interrupted.RequestId, new { fingerprint = fp, state = "attempting" });
            Check((await router.DispatchControllerHandoff(interrupted, CancellationToken.None)).GetProperty("state").GetString() == "attempting" && native.Writes == 1,
                "Crash-before-receipt never replays an attempting handoff");
            var concurrent = job with { RequestId = "concurrent-handoff" };
            type.GetField("Busy")!.SetValue(session, false); type.GetField("Turn")!.SetValue(session, null);
            await Task.WhenAll(router.DispatchControllerHandoff(concurrent, CancellationToken.None), router.DispatchControllerHandoff(concurrent, CancellationToken.None));
            Check(native.Writes == 2, "Concurrent duplicate submissions dispatch only once");
        }
        return checks;
    }
    private sealed class Native(string mode) : INative
    {
        public uint Pid => 1; public int Writes; public string? LastMethod, ExpectedTurn;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            if (method == "thread/read")
            {
                if (mode == "read-failure") throw new IOException("Inert read failure");
                var p = Json(parameters);
                return Task.FromResult(Json(new { thread = new { id = p.GetProperty("threadId").GetString(), cwd = "/Users/pouya/.openclaw/workspace/ai-hil/web",
                    status = new { type = mode is "active" or "wrong-ack" ? "active" : "idle", activeFlags = Array.Empty<string>() } } }));
            }
            if (mode == "before-write") throw new NativeNotSubmitted();
            Writes++; LastMethod = method;
            if (mode == "after-write") throw new IOException("Inert after-write failure");
            if (mode == "rejected") throw new NativeRejected(method);
            if (method == "turn/steer") { ExpectedTurn = Json(parameters).GetProperty("expectedTurnId").GetString(); return Task.FromResult(Json(new { turnId = mode == "wrong-ack" ? "different" : ExpectedTurn })); }
            if (method != "turn/start") throw new Exception("Unexpected handoff native mutation");
            return Task.FromResult(Json(new { turn = new { id = "new-turn" } }));
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No handoff approval reply");
    }
    private sealed class Bot : IBot
    {
        public Task<JsonElement> Call(string m, object p, CancellationToken s, bool effect = false) => throw new Exception("No handoff Telegram effects");
        public Task<JsonElement> Send(long c, int t, string text, CancellationToken s) => throw new Exception("No handoff Telegram effects");
        public Task Edit(long c, int m, string text, CancellationToken s) => throw new Exception("No handoff Telegram effects");
    }
}
