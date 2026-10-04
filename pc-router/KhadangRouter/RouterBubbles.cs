using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    private string RenderBubble(Session session) => session.Bubble.Render(
        session.Carried + session.Elapsed.Elapsed, session.Claude == null ? session.Goal.Footer : null, session.Status);

    // Called under Gate, only at a new native-work boundary, never on steering.
    private void BeginBubble(Session session)
    {
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
            session.PendingBubbles.Enqueue(response);
            if (response.SendUnknown || response.Answer.Parts.Any(p => p.SendUnknown)) { session.Held = true; session.Status = "Held — reconcile uncertain response delivery"; }
        }
    }

    private static void RestoreAnswer(ResponseMessage response, JsonElement saved)
    {
        if (!saved.TryGetProperty("finalAnswer", out var answer)) return; // Legacy progress has no final outbox.
        response.Answer = JsonSerializer.Deserialize<FinalAnswerState>(answer.GetRawText()) ?? throw new InvalidDataException("Missing saved final answer");
        response.Answer.Validate();
    }
    private void CompleteAnswer(Session session)
    {
        try { session.Response.Answer.Complete(); }
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
        ResponseMessage response = null!; string text = ""; int? message; long revision = 0;
        while (true)
        {
            lock (session.Gate)
            {
                // Finish an earlier response before sending the next. Even a turn
                // completed between editor ticks gets its own terminal message.
                while (session.PendingBubbles.TryPeek(out var completed) &&
                    !completed.SendUnknown && completed.Text == completed.LastRendered && completed.Answer.Delivered)
                    session.PendingBubbles.Dequeue();
                response = session.PendingBubbles.TryPeek(out var pending) ? pending : session.Response;
                if (response.SendUnknown || response.Message == null && response.Answer.Parts.Any(p => p.SendUnknown)) return;
                text = ReferenceEquals(response, session.Response) ? RenderBubble(session) : response.Text;
                message = response.Message; revision = session.Revision;
            }
            if (text != response.LastRendered) try
            {
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
                else lock (session.Gate) { response.SendUnknown = true; Persist(session); }
            }
            // Finish/acknowledge progress before the separate final answer. No
            // late edit can overtake it; each part has its own durable intent.
            lock (session.Gate)
                if (response.SendUnknown || response.LastRendered != text ||
                    ReferenceEquals(response, session.Response) && revision != session.Revision) return;
            lock (session.Gate)
                if ((ReferenceEquals(response, session.Response) ? RenderBubble(session) : response.Text) != text) continue;
            foreach (var part in response.Answer.Parts)
            {
                lock (session.Gate)
                {
                    if (part.Message != null) continue;
                    if (part.SendUnknown) return;
                    part.SendUnknown = true; Persist(session);
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
                        session.Held = true; session.Status = "Held — final answer delivery unconfirmed";
                        if (!ReferenceEquals(response, session.Response)) response.Text = RollingBubble.LineTail(text + "\nFinal answer delivery unconfirmed; no automatic resend.", 3900);
                        Persist(session);
                    }
                    return;
                }
            }
            lock (session.Gate) if (ReferenceEquals(response, session.Response)) return;
        }
        void Delivered()
        {
            response.LastRendered = text;
            if (ReferenceEquals(response, session.Response)) session.Dirty = revision != session.Revision;
            Persist(session);
        }
    }
}
