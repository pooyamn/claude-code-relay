using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    private static bool RecoverableObservationHold(Session session) => session.Status is
        "Held — reconcile interrupted turn" or "Held — reconcile native/transport receipts" or
        "Held — Telegram input blocked; inspect native/transport receipts" ||
        session.Status.StartsWith("Held — input ", StringComparison.Ordinal) && session.Status.EndsWith(" not confirmed", StringComparison.Ordinal);

    // Read exact current state, never replay an old update or acknowledge an
    // uncertain native action. The sticky display flag is not an input receipt.
    private bool CanReconcileCodex(Session session) => !session.Initializing && session.Claude == null &&
        !session.PreserveSavedBubble && Connection(session.Native) != false &&
        session.Held && RecoverableObservationHold(session) && ledger.InputUnknown(session.Binding) == 0 &&
        !approvals.Values.Any(a => a.Thread == session.Binding.ThreadId) &&
        !questions.Values.Any(q => q.Thread == session.Binding.ThreadId);

    private async Task ReconcileCodex(Session session, CancellationToken stop)
    {
        if (!await session.Dispatch.WaitAsync(0, stop)) return;
        try
        {
            long revision; string? previousTurn;
            lock (session.Gate)
            {
                if (!CanReconcileCodex(session)) return;
                revision = session.NativeStateRevision; previousTurn = session.Turn;
            }
            var binding = session.Binding;
            var read = await session.Native.Call("thread/read", new { threadId = binding.ThreadId, includeTurns = false }, stop, effect: false);
            var thread = read.GetProperty("thread");
            if (thread.GetProperty("id").GetString() != binding.ThreadId ||
                thread.GetProperty("cwd").GetString() != binding.Workspace) throw new InvalidDataException("Reconciliation identity mismatch");
            var status = thread.GetProperty("status"); var state = status.GetProperty("type").GetString();
            if (state is not ("idle" or "active")) return; // Never enroll/load/fork a missing conversation.
            if (status.TryGetProperty("activeFlags", out var flags) && flags.GetArrayLength() != 0) return;
            var page = await session.Native.Call("thread/turns/list", new { threadId = binding.ThreadId, limit = 1,
                sortDirection = "desc", itemsView = "notLoaded" }, stop, effect: false);
            var turns = page.GetProperty("data");
            if (turns.GetArrayLength() > 1 || state == "active" && turns.GetArrayLength() != 1) throw new InvalidDataException("Invalid bounded turn observation");
            string? turnId = null, turnState = null;
            if (turns.GetArrayLength() == 1)
            {
                turnId = turns[0].GetProperty("id").GetString(); turnState = turns[0].GetProperty("status").GetString();
                if (string.IsNullOrWhiteSpace(turnId) || turnId.Length > 200 || turnId.Any(char.IsControl)) throw new InvalidDataException("Invalid observed turn");
                if (state == "active" && turnState != "inProgress" || state == "idle" && turnState is not ("completed" or "interrupted" or "failed")) return;
            }
            lock (session.Gate)
            {
                if (session.NativeStateRevision != revision || !CanReconcileCodex(session)) return;
                var wasHeld = session.Held;
                var changed = session.Turn != turnId || session.Busy != (state == "active") || wasHeld;
                if (!changed) return;
                ledger.Put("native/reconciled/" + binding.ThreadId, new { binding, previousTurn, turnId, turnState,
                    nativeState = state, previousHold = wasHeld ? session.Status : null,
                    inputReplay = false, at = DateTimeOffset.UtcNow });
                session.Held = false; session.RestoreTurn = null;
                if (state == "active" && session.Turn != turnId) BeginBubble(session);
                session.Turn = turnId; session.Busy = state == "active";
                session.Status = session.Busy ? "Working" : turnState == "completed" ? "Done" : turnState == "interrupted" ? "Stopped" : turnState == "failed" ? "Failed — inspect native session" : "Ready";
                if (!session.Busy) session.Elapsed.Stop();
                // Only finish already-observed prose for the SAME turn. Never
                // invent a final answer for work missed while disconnected.
                if (previousTurn == turnId && turnState == "completed") CompleteAnswer(session);
                if (wasHeld) session.Bubble.Append("\nExact native state reconciled. Telegram input restored; retained messages were not replayed.\n");
                Touch(session);
            }
        }
        finally { session.Dispatch.Release(); }
    }

    private async Task ReconcileCodexSafely(Session session, CancellationToken stop)
    {
        try { await ReconcileCodex(session, stop); }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { throw; }
        catch (Exception error) when (error is IOException or TimeoutException or InvalidDataException or InvalidOperationException or JsonException or KeyNotFoundException or NativeRejected)
        { ledger.Put("native/reconcile-fault/" + session.Binding.ThreadId, new { errorType = error.GetType().Name, at = DateTimeOffset.UtcNow }); }
    }
}
