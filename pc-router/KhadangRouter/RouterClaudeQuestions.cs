using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

public sealed partial class Router
{
    // Notification receipts are separate from model answers and rolling edits.
    // Only a currently pending, exact native request can arm an owner notice.
    private sealed class ClaudeQuestionNotice
    {
        public string Id { get; set; } = "";
        public string Pin { get; set; } = "";
        public long Chat { get; set; }
        public int Topic { get; set; }
        public string Fingerprint { get; set; } = "";
        public string Nonce { get; set; } = "";
        public string Text { get; set; } = "";
        public int? Message { get; set; }
        public bool SendUnknown { get; set; }
        public int? Rejected { get; set; }
        public long RetryNotBefore { get; set; }
    }
    private static string QuestionDigest(string value) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    private static string ClaudeQuestionKey(Session session, string id) => "claude/owner-question/" + session.Binding.ThreadId + "/" + QuestionDigest(id);
    private ClaudeQuestionNotice RestoreClaudeQuestionNotice(Session session, string id, JsonElement request)
    {
        var hash = QuestionDigest(request.GetRawText());
        var notice = ledger.Get(ClaudeQuestionKey(session, id))?.Deserialize<ClaudeQuestionNotice>();
        if (notice == null) return new() { Id=id, Pin=session.Binding.ThreadId, Chat=session.Binding.Chat,
            Topic=session.Binding.Topic, Fingerprint=hash, Nonce=Guid.NewGuid().ToString("N")[..12] };
        if (notice.Id != id || notice.Pin != session.Binding.ThreadId || notice.Chat != session.Binding.Chat ||
            notice.Topic != session.Binding.Topic || notice.Fingerprint != hash || notice.Nonce.Length != 12 ||
            !notice.Nonce.All(Uri.IsHexDigit) || notice.Message is <= 0)
            throw new InvalidDataException("Claude question notice differs from exact pending request");
        return notice;
    }
    private void SaveClaudeQuestionNotice(Session session, ClaudeQuestionNotice notice) => ledger.Put(ClaudeQuestionKey(session, notice.Id), notice);
    private async Task FlushClaudeQuestions(Session session, CancellationToken stop)
    {
        if (session.Claude == null) return;
        foreach (var pair in claudeRequests.Where(p => p.Value.Pin == session.Binding.ThreadId).ToArray())
        {
            ClaudeQuestionNotice notice;
            lock (session.Gate)
            {
                if (!CurrentClaudeRequest(session, pair.Key, out var current)) continue;
                notice = current.Notice;
                if (notice.Message != null || notice.SendUnknown || notice.Rejected != null ||
                    notice.RetryNotBefore > (deliveryClock ?? TimeProvider.System).GetUtcNow().ToUnixTimeSeconds()) continue;
                notice.SendUnknown = true; SaveClaudeQuestionNotice(session, notice); // Intent before HTTP.
            }
            try
            {
                // Owner-action notices bypass automatic answer pacing and are
                // ordinary notified text, never silent code-block bubble edits.
                var result = await telegram.SendAttention(session.Binding.Chat, session.Binding.Topic, notice.Text, stop);
                var message = result.GetProperty("message_id").GetInt32();
                if (message <= 0) throw new InvalidDataException("Invalid owner-question receipt");
                lock (session.Gate) { notice.Message=message; notice.SendUnknown=false; SaveClaudeQuestionNotice(session, notice); }
            }
            catch (TelegramFailure failure)
            {
                lock (session.Gate)
                {
                    if (failure.Code is 400 or 403 or 413 or 429)
                    {
                        notice.SendUnknown=false;
                        if (failure.Code == 429) notice.RetryNotBefore=(deliveryClock ?? TimeProvider.System).GetUtcNow().ToUnixTimeSeconds()+Math.Clamp(failure.RetryAfter,1,3600);
                        else notice.Rejected=failure.Code;
                    }
                    SaveClaudeQuestionNotice(session, notice);
                }
            }
            catch (Exception error) when (error is IOException or InvalidDataException or JsonException or OperationCanceledException)
            { lock (session.Gate) SaveClaudeQuestionNotice(session, notice); } // Unknown initial send is never replayed.
        }
    }
    internal static string RemoveSavedClaudeQuestions(string text) => Regex.Replace(text,
        @"(?m)^Claude (?:question|approval):[^\r\n]*\r?\n[\s\S]*?^/deny [a-f0-9]{12}\r?\n?", "", RegexOptions.CultureInvariant, TimeSpan.FromSeconds(1));
}
