using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    private async Task ResumeCodex(Session session, CancellationToken stop)
    {
        var binding = session.Binding;
        long resumeRevision;
        // Adopt ONLY the durable exact ID before reads, so an observed
        // completion during recovery closes it rather than being discarded.
        lock (session.Gate) {
            if (session.RestoreTurn != null && !session.Held && !session.SendUnknown && ledger.Unknown == 0)
            { session.Turn = session.RestoreTurn; session.Busy = true; session.Status = "Working"; }
            resumeRevision = session.NativeStateRevision;
        }
        // Exclude transport history, not native context. Large controller
        // histories must not be sent through the bounded transport frame.
        var resumed = await session.Native.Call("thread/resume", new { threadId = binding.ThreadId, cwd = binding.Workspace,
            excludeTurns = true, approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user",
            permissions = policy.NativePermissionProfile }, stop);
        VerifyThread(resumed, binding.Workspace, binding.ThreadId, binding.Runtime);
        if (!resumed.GetProperty("thread").TryGetProperty("status", out var status)) return;
        if (status.GetProperty("type").GetString() != "active" && session.RestoreTurn == null) return;
        long revision;
        lock (session.Gate)
        {
            if (session.NativeStateRevision != resumeRevision) { session.RestoreTurn = null; return; }
            // A confirmed active snapshot is not authority to clear an older
            // unknown delivery/interrupted receipt or pending approval.
            if (session.Held || session.SendUnknown || ledger.Unknown != 0) return;
            if (status.TryGetProperty("activeFlags", out var flags) && flags.GetArrayLength() != 0)
            {
                session.Held = true; session.Status = "Held — inspect pending native request"; Touch(session); return;
            }
            revision = session.NativeStateRevision;
        }
        var page = await session.Native.Call("thread/turns/list", new { threadId = binding.ThreadId, limit = 1,
            sortDirection = "desc", itemsView = "notLoaded" }, stop, effect: false);
        var turns = page.GetProperty("data");
        if (turns.GetArrayLength() != 1) throw new InvalidDataException("Active native thread lacks an exact latest turn");
        var turn = turns[0]; var id = turn.GetProperty("id").GetString();
        if (string.IsNullOrWhiteSpace(id) || id.Length > 200 || id.Any(char.IsControl)) throw new InvalidDataException("Invalid native active-turn identity");
        lock (session.Gate)
        {
            if (session.NativeStateRevision != revision || session.Held || session.SendUnknown || ledger.Unknown != 0) { session.RestoreTurn = null; return; }
            if (approvals.Values.Any(a => a.Thread == binding.ThreadId) || questions.Values.Any(q => q.Thread == binding.ThreadId))
            { session.Held = true; session.Status = "Held — inspect pending native request"; Touch(session); return; }
            var advanced = session.RestoreTurn != null && id != session.RestoreTurn;
            if (advanced)
            {
                // Native app/goal work may advance while the observer is down.
                // The exact thread/workspace/security and latest turn are now
                // verified, with no unknown effects or pending native request.
                // Rotate observations; never replay input, approve, or pretend
                // the older response received a final completion.
                session.Status = "Detached — native work advanced while bridge was offline";
                BeginBubble(session); session.RestoreTurn = null;
                session.Turn = id; session.Busy = false;
            }
            if (turn.GetProperty("status").GetString() != "inProgress")
            {
                if (advanced)
                { session.Status = turn.GetProperty("status").GetString() == "completed" ? "Done" : "Stopped";
                  session.Bubble.Append("Native work advanced while the bridge was offline; no input replayed."); Touch(session); }
                else if (session.RestoreTurn != null && turn.GetProperty("status").GetString() is "completed" or "interrupted")
                { session.Turn = id; session.Busy = false; session.Status = turn.GetProperty("status").GetString() == "completed" ? "Done" : "Stopped";
                  if (session.Status == "Done") CompleteAnswer(session); session.RestoreTurn = null; Touch(session); }
                return;
            }
            if (session.Turn == id && session.Busy && session.RestoreTurn == null) return;
            if (session.RestoreTurn == null && !advanced) BeginBubble(session);
            session.RestoreTurn = null; session.Turn = id; session.Busy = true; session.Status = "Working";
            session.Elapsed.Restart(); session.Carried = TimeSpan.Zero;
            if (turn.TryGetProperty("startedAt", out var started) && started.TryGetInt64(out var seconds))
                session.Carried = TimeSpan.FromSeconds(Math.Max(0, DateTimeOffset.UtcNow.ToUnixTimeSeconds() - seconds));
            session.Bubble.Append("Attached to existing native work; no new turn started."); Touch(session);
        }
    }
}
