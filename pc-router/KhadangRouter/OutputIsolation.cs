using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    // Called under the session gate (or during single-threaded restoration).
    // Keep the original uncertain intent and payload, but remove it from active
    // delivery/admission. "Retained" explicitly does NOT mean "delivered".
    private void IsolateOutput(Session session)
    {
        var prefix = "output-retained/" + session.Binding.ThreadId + "/";
        if (!session.OutputRetentionLoaded)
        {
            session.RetainedOutput = int.Parse(ledger.Query("SELECT COUNT(*) FROM meta WHERE substr(key,1,?)=?", prefix.Length, prefix)[0][0]!);
            session.OutputRetentionLoaded = true;
        }
        void Retain(string kind, object value)
        {
            var payload = JsonSerializer.Serialize(value);
            var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(kind + "\n" + payload)));
            var key = prefix + hash;
            if (ledger.Get(key) == null)
            {
                ledger.Put(key, new
                {
                    schema = "ccrelay.retained_output.v1",
                    binding = session.Binding,
                    kind,
                    payload,
                    state = "delivery-unconfirmed",
                    automaticReplay = false,
                    at = DateTimeOffset.UtcNow
                });
                session.RetainedOutput++;
            }
        }
        foreach (var response in session.PendingBubbles.Append(session.Response))
            if (response.SendUnknown && response.Message == null && !response.ProgressSending && !response.ProgressRetained)
            {
                Retain("progress", new { response.Text, response.LastRendered, response.SendUnknown, response.Message });
                response.ProgressRetained = true;
            }
        foreach (var answer in session.PendingAnswers.Concat(session.PendingFiles).Concat(session.PendingBubbles.Select(r => r.Answer)).Append(session.Response.Answer))
        {
            foreach (var part in answer.Parts.Where(p => p.SendUnknown && !p.Sending && !p.Retained))
            { Retain("text", part); part.Retained = true; }
            foreach (var file in answer.Files.Where(f => f.SendUnknown && !f.Sending && !f.Retained))
            { Retain("file", file); file.Retained = true; }
        }
    }
    private static void QueueFiles(Session session, FinalAnswerState answer)
    {
        if (!answer.Completed || !answer.TextSettled || answer.Files.Count == 0) return;
        session.PendingFiles.Enqueue(new FinalAnswerState { Completed = true, Files = answer.Files });
        answer.Files = []; // The move is committed in the same bubble snapshot.
    }
    private void FileNotice(Session session, string text)
    {
        session.PendingAnswers.Enqueue(new FinalAnswerState { Completed = true, Parts = [new() { Part = new(text, []) }] });
        Persist(session);
    }
    private async Task FlushAttachments(Session session, CancellationToken stop)
    {
        FinalAnswerState answer;
        lock (session.Gate)
        {
            IsolateOutput(session);
            while (session.PendingFiles.TryPeek(out var settled) && settled.Settled) session.PendingFiles.Dequeue();
            if (!session.PendingFiles.TryPeek(out answer!)) { Persist(session); return; }
        }
        await FlushFiles(session, answer, stop);
    }
    private void RecordOutputFault(Session session, string lane, Exception error)
    {
        lock (session.Gate)
        {
            session.OutputError = lane + ":" + error.GetType().Name;
            ledger.Put("output-fault/" + session.Binding.ThreadId, new { lane, errorType = error.GetType().Name, at = DateTimeOffset.UtcNow });
            IsolateOutput(session); Persist(session);
        }
    }
    private async Task AttachmentPass(Session session, CancellationToken stop)
    {
        try { await FlushAttachments(session, stop); }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { throw; }
        catch (Exception error) { RecordOutputFault(session, "file", error); }
    }
    private async Task AttachmentLoop(CancellationToken stop)
    {
        var running = new Dictionary<TopicAddress, Task>();
        try
        {
            while (!stop.IsCancellationRequested)
            {
                foreach (var completed in running.Where(x => x.Value.IsCompleted).ToArray())
                { await completed.Value; running.Remove(completed.Key); }
                foreach (var session in sessions.Values.OrderBy(s => s.FileScheduledAt))
                {
                    if (running.Count >= 2) break;
                    if (running.ContainsKey(session.Binding.Address) || session.PreserveSavedBubble || session.Initializing) continue;
                    lock (session.Gate)
                        if (session.PendingFiles.Count == 0) continue;
                    session.FileScheduledAt = DateTimeOffset.UtcNow;
                    running.Add(session.Binding.Address, AttachmentPass(session, stop));
                }
                await Task.Delay(250, stop);
            }
        }
        finally { await Task.WhenAll(running.Values); }
    }
}
