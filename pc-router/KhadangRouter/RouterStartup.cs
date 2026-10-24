using System.Collections.Concurrent;
using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    private async Task AttachBinding(Binding binding, ConcurrentDictionary<IClaudeNative, byte> ownedClaude,
        SemaphoreSlim attachSlots, CancellationToken stop)
    {
        await attachSlots.WaitAsync(stop);
        var session = sessions[binding.Address];
        try
        {
            var native = binding.Runtime == "linux" && binding.Backend == "codex" ? linuxRpc! : rpc;
            Exception? attachmentError = null;
            if (binding.Backend == "claude")
            {
                try
                {
                    session.Claude = await claudeTopics!.Open(binding, stop);
                    ownedClaude.TryAdd(session.Claude, 0);
                    if (!session.Claude.Connected || session.Claude.SessionId != binding.ThreadId)
                        throw new InvalidDataException("Claude adapter does not own the exact selected session");
                }
                catch (Exception error) when (StartupRouteFailure(error, stop))
                {
                    if (session.Claude is { } acquired)
                    { ownedClaude.TryRemove(acquired, out _); await acquired.DisposeAsync(); }
                    session.Claude = new UnavailableClaude(binding.ThreadId);
                    attachmentError = error;
                }
            }
            if (ledger.Get("bubble/" + binding.ThreadId) is { } saved)
            {
                var savedTail = saved.GetProperty("tail").GetString()!;
                session.Bubble.Append(binding.Backend == "claude" ? RemoveSavedClaudeQuestions(savedTail) : savedTail);
                session.Message = saved.GetProperty("message").ValueKind == JsonValueKind.Number ? saved.GetProperty("message").GetInt32() : null;
                // A retained ID came from a confirmed initial send. An edit of
                // that same message may be amended again without duplicating
                // a new message, native input or external action. Keep its
                // original uncertain operation in the display audit.
                session.Response.ProgressRetained = saved.TryGetProperty("progressRetained", out var retainedProgress) && retainedProgress.GetBoolean();
                session.SendUnknown = saved.GetProperty("sendUnknown").GetBoolean() && (session.Message == null || session.Response.ProgressRetained);
                if (saved.GetProperty("busy").GetBoolean() && !saved.GetProperty("held").GetBoolean() &&
                    saved.TryGetProperty("turn", out var previousTurn) && previousTurn.ValueKind == JsonValueKind.String)
                    session.RestoreTurn = previousTurn.GetString();
                // A kernel-authenticated SAME host/native epoch retained active
                // work. This is a UI reattachment, not an interrupted agent.
                // New generations and pre-existing/uncertain holds stay fenced.
                // Custody continuity and input receipt safety are independent.
                // Admission fences an unacknowledged input until its exact echo
                // arrives; it must not manufacture a second, sticky UI hold.
                var continuousClaude = session.Claude is ClaudeWorkerClient { ReattachedGeneration: true };
                session.Held = saved.GetProperty("held").GetBoolean() || saved.GetProperty("busy").GetBoolean() && session.RestoreTurn == null && !continuousClaude;
                session.Status = saved.TryGetProperty("nativeStatus", out var nativeStatus) ? nativeStatus.GetString()! : saved.GetProperty("status").GetString()!;
                // Preserve specific safety holds. Replacing every reason with
                // "interrupted" would make a malformed-event/approval hold
                // look eligible for routine observation reconciliation.
                if (session.Held && !session.Status.StartsWith("Held", StringComparison.Ordinal))
                    session.Status = saved.GetProperty("held").GetBoolean() && saved.GetProperty("status").GetString() is { } heldStatus && heldStatus.StartsWith("Held", StringComparison.Ordinal)
                        ? heldStatus : "Held — reconcile interrupted turn";
                session.Carried = TimeSpan.FromMilliseconds(saved.GetProperty("elapsedMs").GetDouble());
                try { RestorePendingBubbles(session, saved); RestoreAnswer(session.Response, saved); }
                catch (Exception error) when (error is InvalidDataException or JsonException)
                {
                    // Keep the complete opaque original outbox. Do not truncate
                    // it or persist a partially restored replacement.
                    session.PreserveSavedBubble = true; attachmentError = error;
                }
                if (saved.TryGetProperty("lastAnswer", out var lastAnswer)) session.LastAnswer = lastAnswer.GetString()!;
                if (saved.TryGetProperty("claudeDeliveryHold", out var deliveryHold) && deliveryHold.ValueKind == JsonValueKind.Object)
                    session.DeliveryHold = deliveryHold.Deserialize<ClaudeDeliveryHold>();
                // Output uncertainty is retained separately from native admission.
                IsolateOutput(session);
                if (session.Held && saved.GetProperty("status").GetString() is "Held — final answer delivery unconfirmed" or
                    "Held — attachment delivery unconfirmed; no automatic resend" or "Held — reconcile uncertain response delivery" &&
                    session.RetainedOutput > 0 && ledger.InputUnknown(binding) == 0 && session.DeliveryHold == null &&
                    ledger.Get("claude/reset/" + binding.ThreadId) == null) session.Held = false;
                session.Dirty = true;
            }
            if (session.PreserveSavedBubble && session.Claude is { } frozen && frozen is not UnavailableClaude)
            {
                ownedClaude.TryRemove(frozen, out _); await frozen.DisposeAsync();
                session.Claude = new UnavailableClaude(binding.ThreadId);
            }
            sessions[binding.Address] = session;
            if (attachmentError != null) HoldStartupRoute(session, attachmentError);
            else ledger.Exec("DELETE FROM meta WHERE key=?", "startup-held/" + binding.ThreadId);
            if (session.Claude == null) await ResumeCodex(session, stop);
            if (session.Claude is { } claude && claude is not UnavailableClaude && !session.PreserveSavedBubble)
            {
                try
                {
                    session.ClaudeHandler = message => OnClaude(session, message);
                    claude.Notification += session.ClaudeHandler;
                    var revision = session.ClaudeStateRevision;
                    session.ClaudeInfo = await claude.Initialize(stop);
                    lock (session.Gate)
                    {
                        // Only a disconnected *idle* stream, independently renewed
                        // by the protected recovery gate, may shed its stale hold.
                        // Other holds/uncertainties and all native inputs stay intact.
                        if (revision == session.ClaudeStateRevision && policy.LinuxClaude?.GuardedRecovery == true && session.Held &&
                            ledger.Get("bubble/" + binding.ThreadId) is { } priorBubble &&
                            priorBubble.GetProperty("status").GetString() == "Held — Claude stream disconnected" &&
                            session.ClaudeInfo.Value.GetProperty("session_state").GetString() == "idle" &&
                            ledger.Get(LinuxClaudeTopics.RecoveryKey(binding)) is { } recovery &&
                            recovery.GetProperty("binding").Deserialize<Binding>() == binding && recovery.GetProperty("state").GetString() == "connected")
                            session.Held = false;
                        if (revision == session.ClaudeStateRevision)
                            ApplyClaudeState(session, session.ClaudeInfo.Value.GetProperty("session_state").GetString()!);
                        ReleaseClaudeDeliveryHold(session);
                    }
                    if (claude is ClaudeWorkerClient worker) await worker.RestoreRequests(stop);
                    var remoteReceipt = await ClaudeRemoteControl.Enable(claude, binding, ledger, stop);
                    lock (session.Gate)
                    {
                        session.ClaudeRemoteState = "ready"; session.ClaudeRemoteUrl = remoteReceipt.SessionUrl;
                        session.Bubble.Append("\nClaude app: " + remoteReceipt.SessionUrl + "\n"); Touch(session);
                    }
                    ledger.Exec("DELETE FROM meta WHERE key=?", "startup-held/" + binding.ThreadId);
                }
                catch (Exception error) when (StartupRouteFailure(error, stop))
                {
                    claude.Notification -= session.ClaudeHandler;
                    ownedClaude.TryRemove(claude, out _); await claude.DisposeAsync();
                    session.Claude = new UnavailableClaude(binding.ThreadId);
                    HoldStartupRoute(session, error);
                }
            }
            if (session.Claude == null)
            {
                await ReadGoal(session, stop);
                lock (session.Gate)
                    if (session.Busy && session.Goal.Value?.GetProperty("status").GetString() == "active" &&
                        session.Response.Answer.Explicit && !session.Response.Answer.Completed)
                    {
                        CompleteAnswer(session); session.PendingAnswers.Enqueue(session.Response.Answer); session.Response.Answer = new(); Touch(session);
                    }
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { session.PreserveSavedBubble = true; throw; }
        catch (Exception error) when (StartupRouteFailure(error, stop)) { HoldStartupRoute(session, error); }
        finally
        {
            lock (session.Gate)
            {
                session.Initializing = false;
                if (session.InitializationOverflow) HoldStartupRoute(session, new InvalidDataException("Startup event buffer exceeded; exact native reconciliation required"));
                if (!session.PreserveSavedBubble)
                    while (session.InitialEvents.TryDequeue(out var frame)) ObserveCodexSafely(session.Native, frame);
                session.InitialEvents.Clear(); Persist(session);
            }
            attachSlots.Release();
        }
    }
}
