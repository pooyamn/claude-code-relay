using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

internal static class OwnerSteerQuarantineTests
{
    internal static int Run(string root)
    {
        int checks = 0;
        void Check(bool condition, string name) { if (!condition) throw new Exception(name); checks++; }
        var binding = new Binding(-100123, 42, "Existing", "/work/existing", "existing-native", "codex", "linux");
        var parameters = new { threadId = binding.ThreadId, expectedTurnId = "old-completed", input = new[] { new { type = "text", text = "old request" } } };
        foreach (var mode in new[] { "valid", "no-review", "operation", "payload", "binding", "schema", "action", "ack", "replay", "turn", "active", "current", "workspace", "thread", "approval", "evidence", "malformed", "other-kind" })
        {
            using var ledger = new Ledger(Path.Combine(root, "owner-steer-" + mode + ".db"));
            ledger.Bind(binding);
            var operation = ledger.Attempt(mode == "other-kind" ? "native/turn/start" : "native/turn/steer", new { id = 7, parameters });
            ledger.Outcome(operation, "unknown");
            var payload = ledger.Query("SELECT payload FROM operations WHERE id=?", operation)[0][0]!;
            var review = JsonSerializer.SerializeToElement(new {
                schema = "ccrelay.owner_steer_quarantine.v1", operation, binding,
                payloadSha256 = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload))).ToLowerInvariant(),
                action = "retain-unknown-no-replay", deliveryConfirmed = false, replay = false,
                terminalTurn = new { id = "old-completed", status = "completed" }, observedThread = binding.ThreadId,
                observedWorkspace = binding.Workspace, currentTurn = "different-current-turn", ownerApproval = "Owner reviewed recovery", evidenceSha256 = new string('a', 64)
            }).Deserialize<Dictionary<string, JsonElement>>()!;
            void Replace(string key, object? value) => review[key] = JsonSerializer.SerializeToElement(value);
            switch (mode)
            {
                case "operation": Replace("operation", "other"); break;
                case "payload": Replace("payloadSha256", new string('b', 64)); break;
                case "binding": Replace("binding", binding with { Topic = 43 }); break;
                case "schema": Replace("schema", "unreviewed"); break;
                case "action": Replace("action", "retry"); break;
                case "ack": Replace("deliveryConfirmed", true); break;
                case "replay": Replace("replay", true); break;
                case "turn": Replace("terminalTurn", new { id = "other", status = "completed" }); break;
                case "active": Replace("terminalTurn", new { id = "old-completed", status = "inProgress" }); break;
                case "current": Replace("currentTurn", "old-completed"); break;
                case "workspace": Replace("observedWorkspace", "/work/other"); break;
                case "thread": Replace("observedThread", "other"); break;
                case "approval": Replace("ownerApproval", ""); break;
                case "evidence": Replace("evidenceSha256", "not-a-hash"); break;
                case "malformed": review.Remove("terminalTurn"); break;
            }
            if (mode != "no-review") ledger.Put("owner-steer-quarantine/" + operation, review);
            Check(ledger.InputUnknown(binding) == (mode == "valid" ? 0 : 1), "Only exact owner-reviewed completed steer is isolated: " + mode);
            Check(ledger.Unknown == 1 && ledger.Query("SELECT status,result FROM operations WHERE id=?", operation)[0].SequenceEqual(new string?[] { "unknown", null }), "Original uncertain receipt is untouched: " + mode);
            Check(ledger.LifecycleUnknown(binding) == 1, "Review never authorizes native replacement/retirement: " + mode);
            if (mode == "valid")
            {
                Check(ledger.InputUnknown(binding with { Workspace = "/work/other" }) == 1, "Review cannot follow a workspace change");
                Check(ledger.InputUnknown(binding with { Backend = "claude" }) == 1, "Review cannot authorize another backend");
                var fresh = ledger.Attempt("native/turn/steer", new { id = 8, parameters }); ledger.Outcome(fresh, "unknown");
                Check(ledger.InputUnknown(binding) == 1 && ledger.Unknown == 2, "A later unknown input is independently fenced");
            }
        }
        return checks;
    }
}
