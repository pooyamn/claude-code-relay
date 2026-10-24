using System.Text.Json;
using System.Text.Json.Nodes;

namespace KhadangRouter;

public sealed partial class Router
{
    private async Task<JsonElement> DispatchClaudeHandoff(Session session, string text,
        Func<string, string?, string?, string?, string?, JsonElement> result, CancellationToken stop)
    {
        bool reserved = false, mutationPossible = false, startsHeld = false;
        var claude = session.Claude;
        try
        {
            if (claude is not { Connected: true } || claude.SessionId != session.Binding.ThreadId || claude is not IClaudeStateObservation observer)
                return result("retained-unavailable", null, null, null, null);
            long revision;
            lock (session.Gate) revision = session.ClaudeWorkRevision;
            var observation = await observer.ReadState(stop);
            if (observation.GetProperty("session_id").GetString() != session.Binding.ThreadId ||
                observation.GetProperty("pending_requests").GetArrayLength() != 0)
                return result("retained-native-state", null, null, null, null);
            var state = observation.GetProperty("session_state").GetString();
            if (state is not ("idle" or "running")) return result("retained-native-state", null, null, null, null);
            var active = state == "running";
            bool Admitted() => !session.Held && !session.Initializing && !session.PreserveSavedBubble &&
                ReferenceEquals(session.Claude, claude) && claude.Connected && session.ClaudeWorkRevision == revision &&
                session.ClaudeState == state && session.Busy == active && ledger.InputUnknown(session.Binding) == 0 &&
                !claudeRequests.Values.Any(r => r.Pin == session.Binding.ThreadId);
            lock (session.Gate) if (!Admitted()) return result("retained-native-state", null, null, null, null);
            if (!active)
            {
                await starts.WaitAsync(stop); startsHeld = true;
                if (sessions.Values.Count(s => s.Busy || s.Initializing) >= policy.MaximumSessions)
                    return result("retained-capacity", null, null, null, null);
                var wait = lastStart.AddSeconds(policy.StartSpacingSeconds) - DateTimeOffset.UtcNow;
                if (wait > TimeSpan.Zero) await Task.Delay(wait, stop);
            }
            lock (session.Gate)
            {
                if (!Admitted()) return result("retained-native-state", null, null, null, null);
                if (!active) { reserved = true; StartClaudeWork(session); }
                session.ClaudeResultStatus = null;
            }
            var content = JsonSerializer.SerializeToElement(text);
            mutationPossible = true;
            var receipt = await claude.SendNow(session.Binding.ThreadId, content, stop);
            if (receipt.GetProperty("type").GetString() != "user" || receipt.GetProperty("session_id").GetString() != session.Binding.ThreadId ||
                !Guid.TryParseExact(receipt.GetProperty("uuid").GetString(), "D", out _) || receipt.GetProperty("parent_tool_use_id").ValueKind != JsonValueKind.Null ||
                receipt.GetProperty("message").GetProperty("role").GetString() != "user" ||
                !JsonNode.DeepEquals(JsonNode.Parse(content.GetRawText()), JsonNode.Parse(receipt.GetProperty("message").GetProperty("content").GetRawText())))
                throw new InvalidDataException("Claude handoff lacks an exact primary-user UUID/content acknowledgement");
            lock (session.Gate) Touch(session);
            if (!active) lastStart = DateTimeOffset.UtcNow;
            // UUID is Claude's input receipt, NEVER a fabricated Codex turn ID.
            return result("accepted", "now", receipt.GetProperty("uuid").GetString(), null, null);
        }
        catch (Exception error) when (error is IOException or TimeoutException or OperationCanceledException or NativeRejected or InvalidDataException or JsonException or InvalidOperationException or KeyNotFoundException)
        {
            var unsubmitted = !mutationPossible || error is NativeNotSubmitted;
            lock (session.Gate)
            {
                if (reserved && (unsubmitted || error is NativeRejected) && session.ClaudeState == "idle" && !session.Held)
                { session.Busy = false; session.Elapsed.Stop(); session.Status = "Ready"; Touch(session); }
                if (!unsubmitted && error is not NativeRejected)
                { session.Held = true; session.Status = "Held — controller handoff outcome uncertain"; Touch(session); }
            }
            var timedOut = error as ClaudeDeliveryTimeout;
            return result(unsubmitted ? "retained-unsubmitted" : error is NativeRejected ? "rejected" : "unknown",
                null, timedOut?.Uuid, timedOut?.Operation, error.GetType().Name);
        }
        finally { if (startsHeld) starts.Release(); }
    }
}
