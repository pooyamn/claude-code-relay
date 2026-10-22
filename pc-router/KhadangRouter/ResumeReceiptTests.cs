using System.Text.Json;

namespace KhadangRouter;

internal static class ResumeReceiptTests
{
    internal static int Run(string root)
    {
        var checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        var binding = new Binding(-100123, 42, "Target", "/work/target", "11111111-1111-1111-1111-111111111111");
        var parameters = new { threadId = "22222222-2222-2222-2222-222222222222", cwd = "/work/controller", excludeTurns = true,
            approvalPolicy = "never", approvalsReviewer = "user", permissions = ":danger-full-access" };
        var ack = JsonSerializer.SerializeToElement(new { thread = new { id = parameters.threadId, cwd = parameters.cwd }, approvalPolicy = "never" });
        string path = Path.Combine(root, "resume-receipts.db"); string unknown;
        using (var ledger = new Ledger(path))
        {
            var older = ledger.Attempt("native/thread/resume", new { id = 1, parameters }); ledger.Confirm(older, ack);
            unknown = ledger.Attempt("native/thread/resume", new { id = 2, parameters }); ledger.Outcome(unknown, "unknown");
            Check(ledger.InputUnknown(binding) == 1, "Earlier attachment ACK cannot supersede a later timeout");
            var later = ledger.Attempt("native/thread/resume", new { id = 3, parameters });
            Check(ledger.InputUnknown(binding) == 1, "Attempting attachment is not an ACK");
            ledger.Confirm(later, ack);
            Check(ledger.InputUnknown(binding) == 0, "Identical later attachment ACK removes false global input fence");
            Check(ledger.Unknown == 1 && ledger.Query("SELECT status,result FROM operations WHERE id=?", unknown)[0].SequenceEqual(new string?[] { "unknown", null }),
                "Original timeout remains unknown and unmodified, not falsely confirmed");
            var native = ledger.Attempt("native/turn/start", new { parameters }); ledger.Outcome(native, "unknown");
            Check(ledger.InputUnknown(binding) == 1, "A model action is never superseded by an attachment ACK");
        }
        using (var ledger = new Ledger(path)) Check(ledger.InputUnknown(binding) == 1 && ledger.Unknown == 2, "Resume proof survives restart without suppressing uncertain input");
        foreach (var mode in new[] { "thread", "cwd", "approval", "permissions", "extra-input", "history", "wrong-ack-id", "wrong-ack-cwd", "wrong-ack-policy", "rejected" })
        {
            using var ledger = new Ledger(Path.Combine(root, "resume-" + mode + ".db"));
            var value = JsonSerializer.SerializeToElement(parameters).Deserialize<Dictionary<string, JsonElement>>()!;
            if (mode == "thread") value["threadId"] = JsonSerializer.SerializeToElement(binding.ThreadId);
            if (mode == "cwd") value["cwd"] = JsonSerializer.SerializeToElement("/work/other");
            if (mode == "approval") value["approvalPolicy"] = JsonSerializer.SerializeToElement("on-request");
            if (mode == "permissions") value["permissions"] = JsonSerializer.SerializeToElement(":read-only");
            if (mode == "extra-input") value["input"] = JsonSerializer.SerializeToElement("do work");
            if (mode == "history") value["excludeTurns"] = JsonSerializer.SerializeToElement(false);
            var id = ledger.Attempt("native/thread/resume", new { id = 1, parameters = value }); ledger.Outcome(id, "unknown");
            var newer = ledger.Attempt("native/thread/resume", new { id = 2, parameters = mode is "extra-input" or "history" ? (object)value : parameters });
            var response = JsonSerializer.SerializeToElement(new { thread = new { id = mode == "wrong-ack-id" ? binding.ThreadId : parameters.threadId,
                cwd = mode == "wrong-ack-cwd" ? "/work/other" : parameters.cwd }, approvalPolicy = mode == "wrong-ack-policy" ? "on-request" : "never" });
            if (mode == "rejected") ledger.Reject(newer, response); else ledger.Confirm(newer, response);
            Check(ledger.InputUnknown(binding) == 1, "Unproven resume remains globally fenced: " + mode);
        }
        foreach (var mode in new[] { "identical", "old-ack", "changed", "rejected", "extra", "no-ack" })
        {
            using var ledger = new Ledger(Path.Combine(root, "menu-receipt-" + mode + ".db"));
            object Menu(int topic = 42) => new { scope = new { type = "chat_member", chat_id = -100123L, user_id = 456L }, commands = new[] { new { command = "status", description = "Read status " + topic } } };
            var menu = mode == "extra" ? (object)new { scope = new { type = "chat_member", chat_id = -100123L, user_id = 456L }, commands = Array.Empty<object>(), input = "not a menu" } : Menu();
            string? newer = null;
            if (mode == "old-ack") { newer = ledger.Attempt("telegram/setMyCommands", menu); ledger.Confirm(newer, JsonSerializer.SerializeToElement(true)); }
            var id = ledger.Attempt("telegram/setMyCommands", menu); ledger.Outcome(id, "unknown");
            if (mode != "old-ack")
            {
                newer = ledger.Attempt("telegram/setMyCommands", mode == "changed" ? Menu(43) : menu);
                if (mode == "rejected") ledger.Reject(newer, JsonSerializer.SerializeToElement(false));
                else if (mode != "no-ack") ledger.Confirm(newer, JsonSerializer.SerializeToElement(true));
            }
            Check(ledger.InputUnknown(binding) == (mode == "identical" ? 0 : 1), "Only an exact later menu ACK supersedes an old UI-config timeout: " + mode);
            if (mode == "identical")
            {
                Check(ledger.Unknown == 1 && ledger.Query("SELECT status FROM operations WHERE id=?", id)[0][0] == "unknown", "Superseded menu remains unknown in audit without replay or false confirmation");
                var effect = ledger.Attempt("telegram/sendMessage", new { chat_id = binding.Chat, message_thread_id = binding.Topic }); ledger.Outcome(effect, "unknown");
                Check(ledger.InputUnknown(binding) == 1, "Menu proof cannot waive an uncertain user message");
            }
        }
        return checks;
    }
}
