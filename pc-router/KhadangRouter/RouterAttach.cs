using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    private async Task ResumeCodex(Session session, CancellationToken stop)
    {
        var binding = session.Binding;
        // Exclude transport history, not native context. Large controller
        // histories must not be sent through the bounded transport frame.
        var resumed = await session.Native.Call("thread/resume", new { threadId = binding.ThreadId, cwd = binding.Workspace,
            excludeTurns = true, approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user",
            permissions = policy.NativePermissionProfile }, stop);
        VerifyThread(resumed, binding.Workspace, binding.ThreadId, binding.Runtime);
        if (!resumed.GetProperty("thread").TryGetProperty("status", out var status) ||
            status.GetProperty("type").GetString() != "active") return;
        long revision;
        lock (session.Gate)
        {
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
            if (session.NativeStateRevision != revision || session.Held || session.SendUnknown) return;
            if (turn.GetProperty("status").GetString() != "inProgress") return; // Completed while attaching.
            if (session.Turn == id && session.Busy) return;
            BeginBubble(session); session.Turn = id; session.Busy = true; session.Status = "Working";
            session.Elapsed.Restart(); session.Carried = TimeSpan.Zero;
            if (turn.TryGetProperty("startedAt", out var started) && started.TryGetInt64(out var seconds))
                session.Carried = TimeSpan.FromSeconds(Math.Max(0, DateTimeOffset.UtcNow.ToUnixTimeSeconds() - seconds));
            session.Bubble.Append("Attached to existing native work; no new turn started."); Touch(session);
        }
    }
}
