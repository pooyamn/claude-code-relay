using System.Text.Json;

namespace KhadangRouter;

internal static class ClaudeRestartTests
{
    internal static int Run(string root)
    {
        var checks = 0;
        void Check(bool ok, string name) { if (!ok) throw new Exception(name); checks++; }
        for (int mask = 0; mask < 64; mask++)
        {
            var enabled = (mask & 1) != 0; var normal = (mask & 2) != 0; var connected = (mask & 4) != 0;
            var exited = (mask & 8) != 0; var idle = (mask & 16) != 0; var settled = (mask & 32) != 0;
            bool accepted;
            try { ClaudeWorkerHost.RequireDeadOwnerRecovery(enabled, normal, connected, exited, idle, settled); accepted = true; }
            catch (InvalidOperationException) { accepted = false; }
            Check(accepted == (enabled && normal && !connected && exited && idle && settled), "Only exited idle settled owner can recover: " + mask);
        }
        JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
        Check(LinuxClaudeTopics.RecoveryProgressUnknown(Json(new { sendUnknown = true, message = (int?)null })), "Unknown initial progress send remains fenced");
        Check(!LinuxClaudeTopics.RecoveryProgressUnknown(Json(new { sendUnknown = true, message = 7 })), "Known progress edit never blocks exact-owner startup");
        Check(!LinuxClaudeTopics.RecoveryProgressUnknown(Json(new { sendUnknown = true, message = (int?)null, progressRetained = true })), "Retained progress is never automatically resent by startup");
        var uncertain = new FinalAnswerState { Completed = true, Parts = [new() { Part = new("old", []), SendUnknown = true }] };
        Check(LinuxClaudeTopics.RecoveryAnswerUnsettled(Json(uncertain)), "Unretained unknown final remains fenced");
        uncertain.Parts[0].Retained = true;
        Check(!LinuxClaudeTopics.RecoveryAnswerUnsettled(Json(uncertain)), "Retained final cannot hold unrelated native custody");
        using var ledger = new Ledger(Path.Combine(root, "claude-restart-admission.db"));
        var binding = new Binding(-100123, 42, "Existing", "/work/existing", "existing-native", "claude", "linux");
        ledger.Bind(binding);
        var output = ledger.Attempt("telegram/sendMessage", new { chat_id = binding.Chat, message_thread_id = binding.Topic, text = "old output" });
        ledger.Outcome(output, "unknown");
        ClaudeWorkerHost.RequireSourceAdmission(ledger, binding, normalAttachment: true); checks++;
        bool denied = false;
        try { ClaudeWorkerHost.RequireSourceAdmission(ledger, binding, normalAttachment: false); }
        catch (InvalidOperationException) { denied = true; }
        Check(denied, "Explicit provider switch retains its stricter lifecycle fence");
        var other = binding with { Topic = 43, ThreadId = "different-native" }; ledger.Bind(other);
        ledger.Receive(1, Json(new { message = new { chat = new { id = other.Chat }, message_thread_id = other.Topic } }).GetRawText()); ledger.Claim(1);
        ClaudeWorkerHost.RequireSourceAdmission(ledger, binding, normalAttachment: true); checks++;
        ledger.Receive(2, Json(new { message = new { chat = new { id = binding.Chat }, message_thread_id = binding.Topic } }).GetRawText()); ledger.Claim(2);
        denied = false; try { ClaudeWorkerHost.RequireSourceAdmission(ledger, binding, normalAttachment: true); }
        catch (InvalidOperationException) { denied = true; }
        Check(denied, "Own-topic dispatching input still fences native startup");
        ledger.Finish(2, "accepted");
        var input = ledger.Attempt("claude/user/send-now", new { SessionId = binding.ThreadId }); ledger.Outcome(input, "unknown");
        denied = false; try { ClaudeWorkerHost.RequireSourceAdmission(ledger, binding, normalAttachment: true); }
        catch (InvalidOperationException) { denied = true; }
        Check(denied && ledger.Unknown == 2, "Unknown native input always blocks recovery; receipts unchanged");
        return checks;
    }
}
