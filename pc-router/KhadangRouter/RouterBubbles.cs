using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    private static string DisplayStatus(Session session) => session.Held
        ? session.Status.StartsWith("Held", StringComparison.Ordinal) ? session.Status : "Held — Telegram input blocked; inspect native/transport receipts"
        : session.Status;

    private string RenderBubble(Session session) => session.Bubble.Render(
        session.Carried + session.Elapsed.Elapsed, session.Claude == null ? session.Goal.Footer : null, DisplayStatus(session),
        session.RetainedOutput > 0 ? "Delivery: " + session.RetainedOutput + " item(s) retained, unconfirmed; not resent" : null);

    // Called under Gate, only at a new native-work boundary, never on steering.
    private void BeginBubble(Session session)
    {
        session.GoalReplyPending = false; session.GoalReplyExcludedItems.Clear();
        // An empty initial Ready placeholder is not a completed response.
        if (session.Status == "Ready" && session.Turn == null && session.Bubble.Tail.Length == 0 && !session.SendUnknown)
        {
            session.Bubble = new RollingBubble(); session.Dirty = true; return;
        }
        var previous = session.Response;
        previous.Text = RenderBubble(session);
        if (previous.SendUnknown || previous.Message != null || session.Bubble.Tail.Length != 0)
            session.PendingBubbles.Enqueue(previous);
        session.Response = new ResponseMessage();
        session.Bubble = new RollingBubble();
        session.Dirty = true;
    }

    private static void RestorePendingBubbles(Session session, JsonElement saved)
    {
        if (saved.TryGetProperty("goalReplyPending", out var reply)) session.GoalReplyPending = reply.GetBoolean();
        if (saved.TryGetProperty("goalReplyExcludedItems", out var excluded))
            foreach (var value in excluded.EnumerateArray())
            {
                var id = value.GetString();
                if (session.GoalReplyExcludedItems.Count >= 32 || string.IsNullOrEmpty(id) || id.Length > 200 || id.Any(char.IsControl))
                    throw new InvalidDataException("Invalid pending goal-reply observation");
                session.GoalReplyExcludedItems.Add(id);
            }
        if (saved.TryGetProperty("completedItems", out var items))
            foreach (var item in items.EnumerateArray())
            {
                var id = item.GetString()!;
                if (session.CompletedOrder.Count >= 2048 || string.IsNullOrEmpty(id)) throw new InvalidDataException("Invalid completed-item receipt");
                session.CompletedItems.Add(id); session.CompletedOrder.Enqueue(id);
            }
        if (saved.TryGetProperty("pendingAnswers", out var answers))
            foreach (var value in answers.EnumerateArray())
            {
                var answer = JsonSerializer.Deserialize<FinalAnswerState>(value.GetRawText())!; answer.Validate();
                if (!answer.Completed) throw new InvalidDataException("Pending answer lacks a final boundary");
                session.PendingAnswers.Enqueue(answer);
            }
        if (saved.TryGetProperty("pendingFiles", out var files))
            foreach (var value in files.EnumerateArray())
            {
                var batch = value.Deserialize<FinalAnswerState>() ?? throw new InvalidDataException("Invalid attachment batch");
                batch.Validate();
                if (!batch.Completed || batch.Parts.Count != 0) throw new InvalidDataException("Attachments must use the independent file outbox");
                session.PendingFiles.Enqueue(batch);
            }
        if (!saved.TryGetProperty("pendingResponses", out var pending)) return;
        foreach (var receipt in pending.EnumerateArray())
        {
            var text = receipt.GetProperty("text").GetString()!;
            if (string.IsNullOrEmpty(text) || text.Length > 3900) throw new InvalidDataException("Invalid pending response text");
            var response = new ResponseMessage {
                Text = text, LastRendered = receipt.GetProperty("lastRendered").GetString()!,
                Message = receipt.GetProperty("message").ValueKind == JsonValueKind.Null ? null : receipt.GetProperty("message").GetInt32(),
                SendUnknown = receipt.GetProperty("sendUnknown").GetBoolean()
            };
            RestoreAnswer(response, receipt);
            if (receipt.TryGetProperty("progressSuperseded", out var superseded) && superseded.GetBoolean())
            {
                if (response.Message != null || response.SendUnknown) throw new InvalidDataException("Cannot supersede sent/uncertain progress");
                response.ProgressSuperseded = true;
            }
            if (receipt.TryGetProperty("progressRetained", out var retained))
            {
                response.ProgressRetained = retained.GetBoolean();
                if (response.ProgressRetained && !response.SendUnknown) throw new InvalidDataException("Invalid retained progress intent");
            }
            if (response.Message != null && !response.ProgressRetained) response.SendUnknown = false;
            session.PendingBubbles.Enqueue(response);
        }
    }

    private static void RestoreAnswer(ResponseMessage response, JsonElement saved)
    {
        if (!saved.TryGetProperty("finalAnswer", out var answer)) return; // Legacy progress has no final outbox.
        response.Answer = JsonSerializer.Deserialize<FinalAnswerState>(answer.GetRawText()) ?? throw new InvalidDataException("Missing saved final answer");
        response.Answer.Validate();
    }
    internal static object ValidateSavedOutbox(Binding binding, JsonElement saved)
    {
        // Offline structural preflight only. This temporary object never
        // enters routing and Restore* cannot call a transport or native tool.
        var session = new Session(binding, null!);
        RestorePendingBubbles(session, saved); RestoreAnswer(session.Response, saved);
        return new { valid=true, pendingAnswers=session.PendingAnswers.Count, pendingBubbles=session.PendingBubbles.Count,
            uncertain=session.Held || session.Response.Answer.Unknown };
    }
    private void CompleteAnswer(Session session)
    {
        try {
            session.Response.Answer.Complete();
            if (session.Response.Answer.Candidate.Length != 0) session.LastAnswer = RollingBubble.SafeTail(session.Response.Answer.Candidate, 12000);
        }
        catch (InvalidDataException)
        {
            session.Held = true;
            session.Bubble.Append("Final answer delivery held: native text exceeds the delivery bound. Full answer remains in native history.");
        }
    }
    private void ConsiderAnswer(Session session, string text, bool authoritative = false)
    {
        try { session.Response.Answer.Consider(text, authoritative); }
        catch (InvalidDataException)
        { session.Held = true; session.Bubble.Append("Final answer delivery held: text exceeds the delivery bound; full native history retained."); }
    }

    private async Task FlushBubble(Session session, CancellationToken stop)
    {
        if (session.PreserveSavedBubble) return; // Original opaque outbox remains untouched.
        await session.Output.WaitAsync(stop);
        try { await FlushBubbleCore(session, stop); }
        finally { session.Output.Release(); }
    }
    private async Task FlushBubbleCore(Session session, CancellationToken stop)
    {
        lock (session.Gate) { IsolateOutput(session); Persist(session); }
        await FlushClaudeQuestions(session, stop);
        // Keep live progress responsive while a saved goal-answer backlog drains.
        if (session.PendingAnswers.Count > 0) await RefreshBacklogBubble(session, stop);
        // Completed goal answers have a separate durable outbox. Native work
        // and frequent progress edits must not starve their notification.
        if (!await FlushGoalAnswers(session, stop)) return;
        ResponseMessage response = null!; string text = ""; int? message; long revision = 0;
        while (true)
        {
            lock (session.Gate)
            {
                // Finish an earlier response before sending the next. Even a turn
                // completed between editor ticks gets its own terminal message.
                while (session.PendingBubbles.TryPeek(out var completed) &&
                    (completed.ProgressRetained || completed.Message != null && completed.SendUnknown ||
                        !completed.SendUnknown && (completed.ProgressSuperseded || completed.Text == completed.LastRendered)) && completed.Answer.Settled)
                    session.PendingBubbles.Dequeue();
                response = session.PendingBubbles.TryPeek(out var pending) ? pending : session.Response;
                if (!response.ProgressRetained && response.SendUnknown && response.Message == null || response.Answer.Unknown) return;
                text = ReferenceEquals(response, session.Response) ? RenderBubble(session) : response.Text;
                message = response.Message; revision = session.Revision;
            }
            if (!response.ProgressRetained && !response.ProgressSuperseded && text != response.LastRendered) try
            {
                lock (session.Gate) response.ProgressSending = true;
                if (message == null)
                {
                    lock (session.Gate) { response.SendUnknown = true; Persist(session); }
                    var sent = await telegram.SendBubble(session.Binding.Chat, session.Binding.Topic, text, stop);
                    lock (session.Gate) { response.Message = sent.GetProperty("message_id").GetInt32(); response.SendUnknown = false; Persist(session); }
                }
                else await telegram.EditBubble(session.Binding.Chat, message.Value, text, stop);
                lock (session.Gate) { Delivered(); }
            }
            catch (TelegramFailure failure)
            {
                if (failure.Code == 429)
                {
                    lock (session.Gate) { response.SendUnknown = false; Persist(session); }
                    await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(failure.RetryAfter, 1, 60)), stop);
                    return;
                }
                else if (failure.NotModified) lock (session.Gate) { Delivered(); }
                else lock (session.Gate) { response.ProgressSending = false; response.SendUnknown = true; IsolateOutput(session); Persist(session); }
            }
            finally { lock (session.Gate) response.ProgressSending = false; }
            // Finish/acknowledge progress before the separate final answer. No
            // late edit can overtake it; each part has its own durable intent.
            lock (session.Gate)
                if (!response.ProgressRetained && (response.SendUnknown && response.Message == null ||
                    !response.SendUnknown && !response.ProgressSuperseded && response.LastRendered != text) ||
                    ReferenceEquals(response, session.Response) && revision != session.Revision) return;
            lock (session.Gate)
                if ((ReferenceEquals(response, session.Response) ? RenderBubble(session) : response.Text) != text) continue;
            foreach (var part in response.Answer.Parts)
            {
                lock (session.Gate)
                {
                    if (part.Message != null || part.Retained) continue;
                    if (part.SendUnknown) return;
                    part.SendUnknown = true; part.Sending = true; Persist(session);
                }
                try
                {
                    var sent = await telegram.SendAnswer(session.Binding.Chat, session.Binding.Topic, part.Part, stop);
                    lock (session.Gate) { part.Message = sent.GetProperty("message_id").GetInt32(); part.SendUnknown = false; Persist(session); }
                }
                catch (TelegramFailure failure)
                {
                    if (failure.Code == 429)
                    {
                        lock (session.Gate) { part.SendUnknown = false; Persist(session); }
                        await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(failure.RetryAfter, 1, 60)), stop);
                    }
                    else lock (session.Gate)
                    {
                        part.Sending = false; IsolateOutput(session);
                        Persist(session);
                    }
                    return;
                }
                finally { lock (session.Gate) part.Sending = false; }
            }
            lock (session.Gate) { QueueFiles(session, response.Answer); Persist(session); }
            lock (session.Gate) if (ReferenceEquals(response, session.Response)) return;
        }
        void Delivered()
        {
            response.SendUnknown = false;
            response.LastRendered = text;
            if (ReferenceEquals(response, session.Response)) session.Dirty = revision != session.Revision;
            Persist(session);
        }
    }

    private async Task<bool> FlushGoalAnswers(Session session, CancellationToken stop)
    {
        while (true)
        {
            FinalAnswerState answer;
            lock (session.Gate)
            {
                while (session.PendingAnswers.TryPeek(out var delivered) && delivered.Settled) session.PendingAnswers.Dequeue();
                if (!session.PendingAnswers.TryPeek(out answer!)) { Persist(session); return true; }
                if (answer.Unknown) return false;
            }
            foreach (var part in answer.Parts)
            {
                lock (session.Gate)
                {
                    if (part.Message != null || part.Retained) continue;
                    part.SendUnknown = true; part.Sending = true; Persist(session);
                }
                try
                {
                    var sent = await telegram.SendAnswer(session.Binding.Chat, session.Binding.Topic, part.Part, stop);
                    lock (session.Gate) { part.Message = sent.GetProperty("message_id").GetInt32(); part.SendUnknown = false; Persist(session); }
                    // One goal-answer part per editor pass keeps other topics
                    // and the live bubble responsive during backlog recovery.
                    return false;
                }
                catch (TelegramFailure failure)
                {
                    lock (session.Gate)
                    {
                        if (failure.Code == 429) part.SendUnknown = false;
                        else { part.Sending = false; IsolateOutput(session); }
                        Persist(session);
                    }
                    if (failure.Code == 429) await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(failure.RetryAfter, 1, 60)), stop);
                    return false;
                }
                finally { lock (session.Gate) part.Sending = false; }
            }
            lock (session.Gate) { QueueFiles(session, answer); Persist(session); }
        }
    }

    private async Task<bool> FlushFiles(Session session, FinalAnswerState answer, CancellationToken stop)
    {
        foreach (var file in answer.Files)
        {
            lock (session.Gate)
            {
                if (file.Message != null || file.Failure != null || file.Retained) continue;
                if (file.SendUnknown) return false;
            }
            byte[] bytes;
            try { bytes = await fileStore.Read(session.Binding, file.Path, file.Sha256, stop); }
            catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or NativeRejected or NotSupportedException or FormatException or JsonException or TimeoutException or System.ComponentModel.Win32Exception)
            {
                lock (session.Gate)
                {
                    file.Failure = "Project file unavailable, changed, outside the topic, or exceeds 20 MiB";
                    FileNotice(session, "Attachment not sent: " + OutboundFiles.Filename(file.Path) + " — " + file.Failure + ".");
                    Persist(session);
                }
                return false; // Flush the visible failure notice on the next tick.
            }
            lock (session.Gate)
            {
                file.Size = bytes.Length; file.Sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
                file.Document |= !OutboundFiles.Photo(bytes);
                file.SendUnknown = true; file.Sending = true; Persist(session); // Intent BEFORE HTTP.
            }
            try
            {
                JsonElement sent;
                try { sent = await telegram.Upload(session.Binding.Chat, session.Binding.Topic, OutboundFiles.Filename(file.Path), bytes, !file.Document, stop); }
                catch (TelegramFailure rejected) when (rejected.Code == 400 && !file.Document)
                {
                    // Explicit rejection only, never ambiguous timeout fallback.
                    lock (session.Gate) { file.Document = true; Persist(session); }
                    sent = await telegram.Upload(session.Binding.Chat, session.Binding.Topic, OutboundFiles.Filename(file.Path), bytes, false, stop);
                }
                lock (session.Gate) { file.Message = sent.GetProperty("message_id").GetInt32(); file.SendUnknown = false; Persist(session); }
                return false; // One file per scheduling quantum; other topics get a turn.
            }
            catch (TelegramFailure failure)
            {
                lock (session.Gate)
                {
                    if (failure.Code == 429) file.SendUnknown = false;
                    else if (failure.Code is 400 or 403 or 413)
                    {
                        file.SendUnknown = false; file.Failure = "Telegram rejected upload (" + failure.Code + ")";
                        FileNotice(session, "Attachment not sent: " + OutboundFiles.Filename(file.Path) + " — " + file.Failure + ".");
                    }
                    else { file.Sending = false; IsolateOutput(session); }
                    Persist(session);
                }
                if (failure.Code == 429) await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(failure.RetryAfter, 1, 60)), stop);
                return false;
            }
            catch (Exception error) when (error is IOException or InvalidDataException or JsonException or NotSupportedException)
            {
                lock (session.Gate)
                {
                    file.Sending = false; IsolateOutput(session);
                    Persist(session);
                }
                return false;
            }
            finally { lock (session.Gate) file.Sending = false; }
        }
        return true;
    }
    private async Task RefreshBacklogBubble(Session session, CancellationToken stop)
    {
        ResponseMessage response; string text; int? message;
        lock (session.Gate)
        {
            response = session.Response;
            if (response.SendUnknown && response.Message == null || session.PendingAnswers.Any(a => a.Unknown)) return;
            message = response.Message; text = RenderBubble(session);
            if (response.LastRendered == text) return;
            if (message == null) { response.SendUnknown = true; Persist(session); }
        }
        try
        {
            if (message is { } existing) await telegram.EditBubble(session.Binding.Chat, existing, text, stop);
            else
            {
                var sent = await telegram.SendBubble(session.Binding.Chat, session.Binding.Topic, text, stop);
                message = sent.GetProperty("message_id").GetInt32();
            }
            lock (session.Gate) { response.Message = message; response.LastRendered = text; response.SendUnknown = false; Persist(session); }
        }
        catch (TelegramFailure failure) when (failure.NotModified)
        { lock (session.Gate) { response.LastRendered = text; response.SendUnknown = false; Persist(session); } }
        catch (TelegramFailure failure)
        {
            lock (session.Gate) { if (message == null) response.SendUnknown = failure.Code != 429; Persist(session); }
        } // Cosmetic edit may be amended; never replay an uncertain new send.
    }
}
