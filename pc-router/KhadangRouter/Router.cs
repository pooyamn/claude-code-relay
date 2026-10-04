using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;

namespace KhadangRouter;

// Owner-only PC migration adapter. It does not claim company/role gates or
// replace the prepared WSL authorization/admission/deployment components.
public sealed partial class Router(RouterPolicy policy, Ledger ledger, IBot telegram, INative rpc, IAttachments? attachments = null,
    NativeRemote? nativeRemote = null, IClaudeTopics? claudeTopics = null, INative? linuxRpc = null)
{
    private sealed class Session(Binding binding, INative native)
    {
        public Binding Binding { get; } = binding;
        public INative Native { get; } = native;
        public IClaudeNative? Claude;
        public JsonElement? ClaudeInfo;
        public Action<JsonElement>? ClaudeHandler;
        public long ClaudeWorkRevision;
        public long ClaudeStateRevision;
        public string ClaudeState = "unverified";
        public string? ClaudeRemoteState;
        public string? ClaudeRemoteUrl;
        public bool ClaudeHasDelta;
        public string? ClaudeResultStatus;
        public readonly object Gate = new();
        public readonly SemaphoreSlim Dispatch = new(1, 1);
        public RollingBubble Bubble = new();
        public Stopwatch Elapsed = new();
        public TimeSpan Carried;
        public string? Turn;
        public NativeGoal Goal = new(binding.ThreadId);
        public ResponseMessage Response = new();
        public readonly Queue<ResponseMessage> PendingBubbles = new();
        public int? Message { get => Response.Message; set => Response.Message = value; }
        public bool SendUnknown { get => Response.SendUnknown; set => Response.SendUnknown = value; }
        public string Status = "Ready";
        public bool Busy, Dirty, Held;
        public long Revision;
        public readonly Dictionary<string, JsonElement> Items = new();
        public readonly HashSet<string> DeltaItems = new();
        public readonly HashSet<string> CompletedItems = new();
        public readonly Queue<string> CompletedOrder = new();
    }
    private readonly ConcurrentDictionary<TopicAddress, Session> sessions = new();
    private readonly ConcurrentDictionary<long, Task> handlers = new();
    private sealed record Approval(JsonElement Id, string Method, TopicAddress Address, string Thread, string Turn, bool CanApprove);
    private readonly ConcurrentDictionary<string, Approval> approvals = new();
    private sealed record Question(JsonElement Id, TopicAddress Address, string Thread, string Turn, JsonElement Questions,
        Dictionary<string, object> Answers);
    private readonly ConcurrentDictionary<string, Question> questions = new();
    private readonly SemaphoreSlim starts = new(1, 1);
    private readonly NativeQuota quota = new();
    private readonly NativeRemote remote = nativeRemote ?? new();
    private readonly NativeQuota linuxQuota = new();
    private readonly NativeRemote linuxRemote = new();
    private readonly IAttachments attachmentStore = attachments ?? new Attachments(policy, ledger, telegram);
    private DateTimeOffset lastStart = DateTimeOffset.MinValue;

    public async Task Run(CancellationToken stop, bool canary = false)
    {
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(stop);
        stop = lifetime.Token;
        var ownedClaude = new List<IClaudeNative>();
        Task edits = Task.CompletedTask;
        var bindings = ledger.Bindings();
        // Validate the WHOLE registry and bubble destinations before the first
        // native resume. A bad later row must not leave earlier tasks resumed.
        policy.ValidateBindings(bindings);
        if (linuxRpc != null && ReferenceEquals(linuxRpc, rpc))
            throw new InvalidDataException("Windows and Linux native sources must be distinct attested transports");
        if (bindings.Any(b => b.Backend == "claude") && claudeTopics == null ||
            bindings.Any(b => b.Backend == "codex" && b.Runtime == "linux") && linuxRpc == null)
            throw new InvalidDataException("Selected native runtime adapter is unavailable; no backend or session fallback");
        foreach (var binding in bindings)
            if (ledger.Get("bubble/" + binding.ThreadId) is { } receipt)
            {
                var hasChat = receipt.TryGetProperty("chat", out var savedChat);
                var hasTopic = receipt.TryGetProperty("topic", out var savedTopic);
                if (hasChat != hasTopic || hasChat && (savedChat.ValueKind != JsonValueKind.Number ||
                    !savedChat.TryGetInt64(out var chat) || chat != binding.Chat || savedTopic.ValueKind != JsonValueKind.Number ||
                    !savedTopic.TryGetInt32(out var topic) || topic != binding.Topic) || !hasChat && binding.Chat != policy.ChatId)
                    throw new InvalidDataException("Bubble receipt belongs to another chat/topic");
                if (receipt.TryGetProperty("backend", out var backend) && backend.GetString() != binding.Backend ||
                    receipt.TryGetProperty("runtime", out var runtime) && runtime.GetString() != binding.Runtime)
                    throw new InvalidDataException("Bubble receipt belongs to another native backend/runtime");
            }
        try
        {
        foreach (var binding in bindings)
        {
            var native = binding.Runtime == "linux" && binding.Backend == "codex" ? linuxRpc! : rpc;
            var session = new Session(binding, native);
            if (binding.Backend == "claude")
            {
                session.Claude = await claudeTopics!.Open(binding, stop);
                ownedClaude.Add(session.Claude);
                if (!session.Claude.Connected || session.Claude.SessionId != binding.ThreadId)
                    throw new InvalidDataException("Claude adapter does not own the exact selected session");
            }
            else
            {
            // Native context still loads in full; only the historical turn
            // payload is excluded from the transport response. Migrated threads
            // can have hundreds of MB of history, beyond the frame bound.
            var resumed = await native.Call("thread/resume", new { threadId = binding.ThreadId, cwd = binding.Workspace, excludeTurns = true,
                approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", permissions = policy.NativePermissionProfile }, stop);
            VerifyThread(resumed, binding.Workspace, binding.ThreadId, binding.Runtime);
            }
            if (ledger.Get("bubble/" + binding.ThreadId) is { } saved)
            {
                session.Bubble.Append(saved.GetProperty("tail").GetString()!);
                session.Message = saved.GetProperty("message").ValueKind == JsonValueKind.Number ? saved.GetProperty("message").GetInt32() : null;
                session.SendUnknown = saved.GetProperty("sendUnknown").GetBoolean();
                session.Held = saved.GetProperty("held").GetBoolean() || saved.GetProperty("busy").GetBoolean();
                session.Status = session.Held ? "Held — reconcile interrupted turn" : saved.GetProperty("status").GetString()!;
                session.Carried = TimeSpan.FromMilliseconds(saved.GetProperty("elapsedMs").GetDouble());
                RestorePendingBubbles(session, saved);
                session.Dirty = true;
            }
            sessions[binding.Address] = session;
            if (session.Claude is { } claude)
            {
                session.ClaudeHandler = message => OnClaude(session, message);
                claude.Notification += session.ClaudeHandler;
                var revision = session.ClaudeStateRevision;
                session.ClaudeInfo = await claude.Initialize(stop);
                lock (session.Gate)
                    if (revision == session.ClaudeStateRevision)
                        ApplyClaudeState(session, session.ClaudeInfo.Value.GetProperty("session_state").GetString()!);
                var remoteReceipt = await ClaudeRemoteControl.Enable(claude, binding, ledger, stop);
                lock (session.Gate)
                {
                    session.ClaudeRemoteState = "ready"; session.ClaudeRemoteUrl = remoteReceipt.SessionUrl;
                    session.Bubble.Append("\nClaude app: " + remoteReceipt.SessionUrl + "\n"); Touch(session);
                }
            }
        }
        rpc.Notification += OnNative;
        if (linuxRpc != null) linuxRpc.Notification += OnLinuxNative;
        if (sessions.Count == 0) await CreateLg(stop);
        foreach (var session in sessions.Values.Where(s => s.Claude == null)) await ReadGoal(session, stop);
        edits = Task.Run(() => EditLoop(stop), stop);
            await Menus(stop);
            if (canary && ledger.Get("native-canary") == null)
            {
                ledger.Put("native-canary", new { state = "attempting", at = DateTimeOffset.UtcNow });
                var address = sessions.Keys.Single();
                if (address.Chat != policy.ChatId || address.Topic <= 0) throw new InvalidOperationException("Deployment canary requires the single primary-forum binding");
                var sample = JsonSerializer.SerializeToElement(new { message = new { from = new { id = policy.OwnerId, is_bot = false },
                    chat = new { id = address.Chat, is_forum = true }, message_thread_id = address.Topic, message_id = 0,
                    text = "Router deployment verification: use the native tool to run whoami /user, then reply exactly PC-RELAY-OK. Do not change files, settings, services or credentials." } });
                ledger.Receive(-1, sample.GetRawText());
                if (ledger.Claim(-1)) await Handle(-1, sample, stop);
            }
            while (!stop.IsCancellationRequested)
            {
                JsonElement batch;
                try { batch = await telegram.Call("getUpdates", new { offset = ledger.Offset, timeout = 25, limit = 50,
                    allowed_updates = new[] { "message" } }, stop); }
                catch (TelegramFailure error) when (error.Code is 0 or 429)
                {
                    // Poll reads are repeatable. A provider cooldown is not a
                    // reason to retry an unknown send, turn or topic creation.
                    await Task.Delay(TimeSpan.FromSeconds(error.Code == 429 ? Math.Clamp(error.RetryAfter, 1, 60) : 3), stop);
                    continue;
                }
                foreach (var update in batch.EnumerateArray()) ledger.Receive(update.GetProperty("update_id").GetInt64(), update.GetRawText());
                foreach (var item in ledger.Pending())
                {
                    if (!ledger.Claim(item.Id)) continue;
                    var task = Handle(item.Id, item.Payload, stop);
                    handlers[item.Id] = task;
                }
                foreach (var done in handlers.Where(pair => pair.Value.IsCompleted).ToArray()) handlers.TryRemove(done.Key, out _);
                StatusFile();
            }
        }
        finally
        {
            lifetime.Cancel();
            rpc.Notification -= OnNative;
            if (linuxRpc != null) linuxRpc.Notification -= OnLinuxNative;
            foreach (var session in sessions.Values)
                if (session.Claude is { } claude)
                {
                    claude.Notification -= session.ClaudeHandler;
                }
            await Task.WhenAll(ownedClaude.Distinct<IClaudeNative>(ReferenceEqualityComparer.Instance).Select(c => c.DisposeAsync().AsTask()));
            try { await Task.WhenAll(handlers.Values.Append(edits)); } catch (OperationCanceledException) { }
        }
    }

    private async Task CreateLg(CancellationToken stop)
    {
        // Verify the target forum and Manage Topics before ANY creation.
        var chat = await telegram.Call("getChat", new { chat_id = policy.ChatId }, stop);
        if (!chat.TryGetProperty("is_forum", out var forum) || !forum.GetBoolean()) throw new InvalidOperationException("Khadang target is not a forum");
        var member = await telegram.Call("getChatMember", new { chat_id = policy.ChatId, user_id = policy.BotId }, stop);
        if (member.GetProperty("status").GetString() != "administrator" ||
            !member.TryGetProperty("can_manage_topics", out var right) || !right.GetBoolean()) throw new InvalidOperationException("Khadang lacks Manage Topics");
        // Unknown creation is NOT retried after crash/timeout. It needs evidence.
        if (ledger.Unknown != 0) throw new InvalidOperationException("Uncertain prior operation; reconcile before creating a topic");
        var workspace = policy.WorkspaceRoot + "\\lg-magic"; policy.Workspace(workspace);
        var progress = ledger.Get("lg-provision");
        if (progress is { } prior && prior.GetProperty("phase").GetString() is "starting-native" or "creating-topic")
            throw new InvalidOperationException("Interrupted LG creation requires receipt reconciliation; refusing duplicate creation");
        string id;
        if (progress is { } existing)
        {
            id = existing.GetProperty("threadId").GetString()!;
            var resumed = await rpc.Call("thread/resume", new { threadId = id, cwd = workspace, excludeTurns = true, approvalPolicy = policy.NativeApprovalPolicy,
                approvalsReviewer = "user", permissions = policy.NativePermissionProfile }, stop);
            VerifyThread(resumed, workspace, id);
        }
        else
        {
        ledger.Put("lg-provision", new { phase = "starting-native" });
        var created = await rpc.Call("thread/start", new { cwd = workspace, approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", permissions = policy.NativePermissionProfile,
            developerInstructions = "You own the LG Magic Remote subtask on this Windows PC. Read LG-SUBTASK.json and repository instructions. " +
                "Never access router credentials, impersonate other roles, change bot wiring or elevate privileges. " +
                "Do not reboot/log off/lock the PC or modify UAC without explicit owner approval. Keep updates short. " +
                "Use native tools and preserve exact task context. Privileged deployments need owner approval. Do not spawn agents unless the user explicitly requests it." }, stop);
        VerifyThread(created, workspace);
        id = created.GetProperty("thread").GetProperty("id").GetString()!;
        // Codex 0.160.0 creates no resumable rollout until history exists.
        // An inert history checkpoint (not inference) makes the confirmed
        // thread durable BEFORE a Telegram topic can reference it.
        ledger.Put("lg-provision", new { phase = "checkpointing-native", threadId = id });
        await rpc.Call("thread/inject_items", new { threadId = id, items = new[] { new {
            type = "message", role = "user", content = new[] { new { type = "input_text",
                text = "[Router provisioning checkpoint, not a new owner task.] LG Magic Remote is assigned to this native Windows PC thread. " +
                    "Read LG-SUBTASK.json when the owner asks you to work. No external action is authorized by this checkpoint." } } } } }, stop);
        var persisted = await rpc.Call("thread/read", new { threadId = id, includeTurns = true }, stop, effect: false);
        if (persisted.GetProperty("thread").GetProperty("id").GetString() != id) throw new InvalidOperationException("Native persistence readback mismatch");
        ledger.Put("lg-provision", new { phase = "native-created", threadId = id });
        }
        int topicId;
        if (progress is { } receipt && receipt.GetProperty("phase").GetString() is "topic-created" or "bound") topicId = receipt.GetProperty("topicId").GetInt32();
        else
        {
            ledger.Put("lg-provision", new { phase = "creating-topic", threadId = id });
            var topic = await telegram.Call("createForumTopic", new { chat_id = policy.ChatId, name = "LG Magic Remote · PC" }, stop, effect: true);
            topicId = topic.GetProperty("message_thread_id").GetInt32();
            ledger.Put("lg-provision", new { phase = "topic-created", threadId = id, topicId });
        }
        var binding = new Binding(policy.ChatId, topicId, "LG Magic Remote · PC", workspace, id);
        ledger.Bind(binding); sessions[binding.Address] = new Session(binding, rpc);
        ledger.Put("lg-provision", new { phase = "bound", threadId = id, topicId });
        await telegram.Send(policy.ChatId, topicId, "LG Magic Remote now has its own PC session. Source and handoff are in " + workspace +
            ". Receiver 0.2.18 is running; TV uses PC 10.0.0.35 / HDMI 3. Messages steer the active native Codex turn. " +
            "Khadang no longer connects to Mac sessions. /help shows available controls.", stop);
        StatusFile();
    }

    private async Task Handle(long updateId, JsonElement update, CancellationToken stop)
    {
        Session? target = null;
        try
        {
            if (!update.TryGetProperty("message", out var message) || !policy.OwnerMessage(message)) { ledger.Finish(updateId, "denied"); return; }
            if (!policy.TryAddress(message, out var address)) { ledger.Finish(updateId, "denied"); return; }
            if (!sessions.TryGetValue(address, out var session))
            {
                if (address.Topic != 1) await telegram.Send(address.Chat, address.Topic, "This chat/topic has no activated PC session. Migration is pending; no message was sent to a model or another session.", stop);
                ledger.Finish(updateId, "unbound"); return;
            }
            target = session;
            if (session.Claude != null) { await HandleClaude(updateId, message, session, stop); return; }
            IReadOnlyList<AttachmentReference> references;
            try { references = Attachments.References(message); }
            catch (Exception error) when (error is InvalidOperationException or KeyNotFoundException) { throw new AttachmentFailure("Malformed attachment metadata; original update retained"); }
            var hasText = message.TryGetProperty("text", out var textElement);
            var hasCaption = message.TryGetProperty("caption", out var caption);
            if (references.Count > 0 && message.TryGetProperty("media_group_id", out _))
                throw new AttachmentFailure("Album references retained; atomic multi-message assembly is pending. No partial album sent.");
            if (hasText && hasCaption || hasText && textElement.ValueKind != JsonValueKind.String || hasCaption && caption.ValueKind != JsonValueKind.String)
                throw new AttachmentFailure("Malformed message text/caption; original update retained");
            if (!hasText && references.Count == 0) throw new AttachmentFailure("Unsupported message content; original update retained. No empty prompt sent.");
            var text = hasText ? textElement.GetString()! : hasCaption ? caption.GetString()! : "";
            if (references.Count == 0 && text.TrimStart().StartsWith('/'))
            {
                // Account reads do not mutate a turn. Don't hold the session
                // dispatch lock across a network quota read: owner steering,
                // interrupt and status must remain usable while it is pending.
                var token = text.Trim().Split((char[]?)null, 2, StringSplitOptions.RemoveEmptyEntries)[0].Split('@')[0];
                if (token.Equals("/limits", StringComparison.OrdinalIgnoreCase) || token.Equals("/remote", StringComparison.OrdinalIgnoreCase))
                {
                    await Control(session, text, stop); ledger.Finish(updateId, "control"); return;
                }
                await session.Dispatch.WaitAsync(stop);
                try { await Control(session, text, stop); ledger.Finish(updateId, "control"); return; }
                finally { session.Dispatch.Release(); }
            }
            string? mediaTurn = null;
            IReadOnlyList<StagedAttachment> files = [];
            if (references.Count > 0)
            {
                lock (session.Gate)
                {
                    if (session.Held || ledger.Unknown != 0 || session.Busy && session.Turn == null)
                        throw new AttachmentFailure("Native input identity is unconfirmed; attachment held before download");
                    mediaTurn = session.Busy ? session.Turn : null;
                }
                // Do not hold the turn/control lock during a network download.
                // Recheck the arrival turn below; never convert stale media
                // steering into a fresh model turn after it ends.
                try { files = await attachmentStore.Stage(message, session.Binding, updateId, stop); }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException or TelegramFailure or NotSupportedException or
                    JsonException or InvalidOperationException or KeyNotFoundException)
                { throw new AttachmentFailure("Attachment download/staging failed (" + error.GetType().Name + "); original reference retained"); }
            }
            await session.Dispatch.WaitAsync(stop);
            try
            {
                string? active;
                lock (session.Gate)
                {
                    if (session.Held || ledger.Unknown != 0) throw new InvalidOperationException("Uncertain prior effect; input held for reconciliation");
                    active = session.Busy ? session.Turn : null;
                    if (mediaTurn != null && active != mediaTurn) throw new AttachmentFailure("Active turn ended or changed during attachment download; staged files held, no fresh-turn fallback");
                    if (session.Busy && active == null) throw new InvalidOperationException("Native turn identity not yet confirmed; no queue fallback");
                }
                var input = Attachments.Input(policy.OwnerId, message.GetProperty("message_id").GetInt64(), text, files, session.Binding.Runtime);
                if (active != null)
                {
                    var receipt = await session.Native.Call("turn/steer", new { threadId = session.Binding.ThreadId, expectedTurnId = active, input }, stop);
                    NativeEventView.VerifySteer(receipt, active);
                    lock (session.Gate) { session.Bubble.Append("\n↪ New owner message steered into this turn.\n"); Touch(session); }
                }
                else
                {
                    await starts.WaitAsync(stop);
                    try
                    {
                        if (sessions.Values.Count(s => s.Busy) >= policy.MaximumSessions) throw new InvalidOperationException("Active session cap reached; input held");
                        var wait = lastStart.AddSeconds(policy.StartSpacingSeconds) - DateTimeOffset.UtcNow;
                        if (wait > TimeSpan.Zero) await Task.Delay(wait, stop);
                        lock (session.Gate)
                        {
                            BeginBubble(session); session.Elapsed.Restart(); session.Carried = TimeSpan.Zero;
                            session.Status = "Working"; session.Busy = true; session.Turn = null; session.Items.Clear(); session.DeltaItems.Clear(); session.CompletedItems.Clear(); session.CompletedOrder.Clear(); Touch(session);
                        }
                        var result = await session.Native.Call("turn/start", new { threadId = session.Binding.ThreadId, input }, stop);
                        var turn = result.GetProperty("turn").GetProperty("id").GetString();
                        lock (session.Gate) { if (session.Status == "Working") { session.Turn = turn; session.Busy = true; } }
                        lastStart = DateTimeOffset.UtcNow;
                    }
                    finally { starts.Release(); }
                }
                ledger.Finish(updateId, "accepted");
            }
            finally { session.Dispatch.Release(); }
        }
        catch (AttachmentFailure error)
        {
            // Known pre-native failure, not an ambiguous model action. Preserve
            // the current turn/goal and keep subsequent owner inputs usable.
            ledger.Finish(updateId, "held-media");
            if (target != null) lock (target.Gate) { target.Bubble.Append("\nAttachment input " + updateId + " held: " + error.Message + "\n"); Touch(target); }
        }
        catch (Exception error) when (error is not OperationCanceledException)
        {
            ledger.Finish(updateId, error is NativeRejected ? "rejected" : "held-no-replay");
            if (target != null)
                lock (target.Gate)
                {
                    target.Held = error is not NativeRejected;
                    target.Status = "Held — input " + updateId + " not confirmed";
                    target.Bubble.Append("\nInput " + updateId + " was not confirmed: " + error.GetType().Name + ". No automatic replay or queued fallback. /status shows the exact session.\n");
                    Touch(target);
                }
            // No native retry, fresh-thread fallback, or model-queue conversion.
            File.WriteAllText(Path.Combine(policy.StateDirectory, "input-held-" + updateId + ".json"), JsonSerializer.Serialize(new {
                updateId, errorType = error.GetType().Name, state = "held-no-replay", at = DateTimeOffset.UtcNow }));
        }
    }

    private async Task Control(Session session, string text, CancellationToken stop)
    {
        var rpc = session.Native;
        var quota = session.Binding.Runtime == "linux" ? linuxQuota : this.quota;
        var remote = session.Binding.Runtime == "linux" ? linuxRemote : this.remote;
        var parts = text.Trim().Split((char[]?)null, 2, StringSplitOptions.RemoveEmptyEntries);
        var command = parts[0].Split('@');
        if (command.Length > 1 && !command[1].Equals(policy.BotUsername, StringComparison.OrdinalIgnoreCase)) return;
        var argument = parts.Length > 1 ? parts[1].Trim() : "";
        string answer;
        switch (command[0].ToLowerInvariant())
        {
            case "/help": answer = "PC Codex controls: /status, /limits, /remote, /cancel, /goal [objective | pause | resume | clear], /model [id], /effort <level>, /approve <nonce>, /deny <nonce>, /answer <nonce> <question-id> <text>. Photos and files download into a protected read-only cache (hosted Telegram limit 20 MB); captions stay with them. Images use native localImage; audio/video are files, not verified transcripts. Native Claude routing, large-file transport and albums remain pending; no Mac fallback is permitted."; break;
            case "/status": answer = "PC session: " + session.Binding.Name + "\nNative thread: " + session.Binding.ThreadId + "\n" +
                (session.Held ? "Held — reconcile native/transport receipts before continuing." : session.Busy ? "Working; new messages steer this turn." : "Idle.") + "\nHeld/unknown operations: " + ledger.Unknown; break;
            case "/cancel":
                string? turn; lock (session.Gate) turn = session.Turn;
                if (turn == null || !session.Busy) { answer = "No active native turn."; break; }
                await rpc.Call("turn/interrupt", new { threadId = session.Binding.ThreadId, turnId = turn }, stop);
                answer = "Interrupt requested; waiting for the native stopped state."; break;
            case "/goal":
                answer = await GoalControl(session, argument, stop); break;
            case "/limits":
                await quota.Read(rpc, stop);
                ledger.Put(NativeStateKey("native/quota", session.Binding.Runtime), quota.Snapshot);
                answer = quota.Render(); break;
            case "/remote":
                await remote.Read(rpc, stop);
                ledger.Put(NativeStateKey("native/remote", session.Binding.Runtime), remote.Snapshot);
                answer = remote.Render(); break;
            case "/model":
                if (argument.Length == 0)
                {
                    var models = await rpc.Call("model/list", new { }, stop, effect: false);
                    answer = "Native models: " + string.Join(", ", models.GetProperty("data").EnumerateArray().Select(m => m.GetProperty("id").GetString()));
                }
                else
                {
                    var models = await rpc.Call("model/list", new { }, stop, effect: false);
                    if (!models.GetProperty("data").EnumerateArray().Any(m => m.GetProperty("id").GetString() == argument)) { answer = "That model is not in the native catalog."; break; }
                    await rpc.Call("thread/settings/update", new { threadId = session.Binding.ThreadId, model = argument }, stop);
                    var readback = await rpc.Call("thread/read", new { threadId = session.Binding.ThreadId, includeTurns = false }, stop, effect: false);
                    answer = readback.GetProperty("thread").GetProperty("model").GetString() == argument ?
                        "Native model verified: " + argument + "." : "Model change accepted, but readback differs; not verified.";
                }
                break;
            case "/effort":
                if (!new[] { "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra" }.Contains(argument)) { answer = "Specify a reasoning level supported by the selected model."; break; }
                await rpc.Call("thread/settings/update", new { threadId = session.Binding.ThreadId, effort = argument }, stop);
                var effortRead = await rpc.Call("thread/read", new { threadId = session.Binding.ThreadId, includeTurns = false }, stop, effect: false);
                answer = effortRead.GetProperty("thread").GetProperty("reasoningEffort").GetString() == argument ?
                    "Native reasoning effort verified: " + argument + "." : "Effort change accepted, but readback differs; not verified."; break;
            case "/approve": case "/deny":
                if (!approvals.TryGetValue(argument, out var request) || request.Address != session.Binding.Address ||
                    request.Thread != session.Binding.ThreadId || request.Turn != session.Turn || !session.Busy)
                { answer = "Approval is missing, stale, or belongs to another session."; break; }
                if (command[0] == "/approve" && !request.CanApprove) { answer = "Full request exceeds the bubble's review limit. Review in the native PC client; Telegram can only /deny this request."; break; }
                if (!approvals.TryRemove(argument, out _)) { answer = "Decision already consumed."; break; }
                var approvalEffect = ledger.Attempt("native/approval-reply", new { nonce = argument, request.Id, request.Thread, request.Turn, decision = command[0] });
                await rpc.Reply(request.Id, new { decision = command[0] == "/approve" ? "accept" : "decline" }, stop);
                ledger.Outcome(approvalEffect, "sent-await-native-evidence");
                answer = "Decision sent to that exact native request; no automatic replay."; break;
            case "/answer":
                var response = argument.Split(' ', 3, StringSplitOptions.RemoveEmptyEntries);
                if (response.Length != 3 || !questions.TryGetValue(response[0], out var question) || question.Address != session.Binding.Address ||
                    question.Thread != session.Binding.ThreadId || question.Turn != session.Turn || !session.Busy)
                { answer = "Use /answer <nonce> <question-id> <text> for a current request in this topic."; break; }
                if (!question.Questions.EnumerateArray().Any(q => q.GetProperty("id").GetString() == response[1] &&
                    (!q.TryGetProperty("isSecret", out var secret) || !secret.GetBoolean()))) { answer = "Unknown question, or secret input requires the native PC client."; break; }
                question.Answers[response[1]] = new { answers = new[] { response[2] } };
                if (question.Answers.Count == question.Questions.GetArrayLength())
                {
                    if (!questions.TryRemove(response[0], out _)) { answer = "Answers already consumed."; break; }
                    var effect = ledger.Attempt("native/question-reply", new { nonce = response[0], question.Thread, question.Turn });
                    await rpc.Reply(question.Id, new { answers = question.Answers }, stop);
                    ledger.Outcome(effect, "sent-await-native-evidence"); answer = "Answers sent to that exact native request.";
                }
                else answer = "Answer recorded. Remaining question IDs: " + string.Join(", ", question.Questions.EnumerateArray().Select(q => q.GetProperty("id").GetString()).Where(q => !question.Answers.ContainsKey(q!)));
                break;
            default: answer = "That control is not activated. /help lists the PC controls; commands are never sent to the model as prompts."; break;
        }
        // Commands share the rolling receipt, including while idle. A separate
        // command reply would recreate the multi-message UI the owner rejected.
        lock (session.Gate) { session.Bubble.Append("\n" + answer + "\n"); Touch(session); }
    }

    private async Task<bool> ReadGoal(Session session, CancellationToken stop)
    {
        var revision = session.Goal.Revision;
        try
        {
            var reply = await session.Native.Call("thread/goal/get", new { threadId = session.Binding.ThreadId }, stop, effect: false);
            session.Goal.Apply(reply.GetProperty("goal"), revision);
            lock (session.Gate) Touch(session);
            return session.Goal.Known;
        }
        catch (Exception error) when (error is NativeRejected or IOException or InvalidDataException or KeyNotFoundException or InvalidOperationException or TimeoutException)
        {
            session.Goal.Unavailable(revision); lock (session.Gate) Touch(session); return false;
        }
    }

    private async Task<string> GoalControl(Session session, string argument, CancellationToken stop)
    {
        GoalCommand command;
        try { command = GoalCommand.Parse(argument); }
        catch (InvalidDataException error) { return error.Message + " No goal change sent."; }
        if (!await ReadGoal(session, stop)) return "Goal status unavailable. No goal change sent.";
        if (command.Action == "status") return session.Goal.Footer is { } line ? "Goal: " + line : "No ongoing goal.";
        var current = session.Goal.Value;
        if (command.Action is "pause" or "resume" && (current == null || current.Value.GetProperty("status").GetString() == "complete"))
            return "No resumable goal. Set a new objective explicitly; a completed goal is not recreated.";
        if (command.Action is "set" or "resume" && (session.Held || ledger.Unknown != 0))
            return "Goal activation held: reconcile uncertain effects first. No change sent.";
        var revision = session.Goal.Revision;
        var method = command.Action == "clear" ? "thread/goal/clear" : "thread/goal/set";
        object parameters = command.Action switch {
            "clear" => new { threadId = session.Binding.ThreadId },
            "set" => new { threadId = session.Binding.ThreadId, objective = command.Objective, status = "active" },
            _ => new { threadId = session.Binding.ThreadId, status = command.Action == "pause" ? "paused" : "active" }
        };
        var reply = await session.Native.Call(method, parameters, stop);
        try
        {
            if (command.Action == "clear")
            {
                if (!await ReadGoal(session, stop)) return "Goal clear acknowledged; current state unavailable. Not retried.";
                return "Goal clear acknowledged. " + (session.Goal.Footer is { } remaining ? "Current goal: " + remaining : "No goal remains.");
            }
            session.Goal.Apply(reply.GetProperty("goal"), revision);
            var expectedStatus = command.Action == "pause" ? "paused" : "active";
            var returned = reply.GetProperty("goal");
            if (returned.GetProperty("status").GetString() != expectedStatus ||
                command.Action == "set" && returned.GetProperty("objective").GetString() != command.Objective)
                return "Goal change acknowledged but requested state differs. Use /goal status; no automatic replay.";
            lock (session.Gate) Touch(session);
            return "Goal control acknowledged. Goal: " + session.Goal.Footer +
                (command.Action == "pause" ? "\nThe current turn was not interrupted; running tools may still be active." : "");
        }
        catch (Exception error) when (error is InvalidDataException or KeyNotFoundException or InvalidOperationException)
        {
            session.Goal.Unavailable(revision); lock (session.Gate) Touch(session);
            return "Goal change acknowledged but state is unverified. Use /goal status; no automatic replay.";
        }
    }

    private void OnNative(JsonElement message) => ObserveCodex(rpc, message);
    private void OnLinuxNative(JsonElement message) => ObserveCodex(linuxRpc!, message);
    private void ObserveCodex(INative source, JsonElement message)
    {
        var remote = ReferenceEquals(source, rpc) ? this.remote : linuxRemote;
        var quota = ReferenceEquals(source, rpc) ? this.quota : linuxQuota;
        remote.Observe(message, source.Pid);
        if (!message.TryGetProperty("method", out var methodElement) || !message.TryGetProperty("params", out var parameters)) return;
        var method = methodElement.GetString()!;
        // Global remote state has no thread. Malformed optional diagnostics
        // must not fall through to thread routing and disconnect the stream.
        if (method == "remoteControl/status/changed" && !message.TryGetProperty("id", out _)) return;
        if (!message.TryGetProperty("id", out _) && (method is "account/rateLimits/updated" or "account/updated"))
        {
            // Account-wide notifications have no threadId. They invalidate the
            // catalog before thread routing; a sparse update cannot bless an
            // old bucket, recover spend permission or win a delayed-read race.
            quota.Invalidate(); ledger.Put(NativeStateKey("native/quota", ReferenceEquals(source, rpc) ? "windows" : "linux"), quota.Snapshot); return;
        }
        if (!parameters.TryGetProperty("threadId", out var id)) return;
        var session = sessions.Values.FirstOrDefault(s => s.Claude == null && ReferenceEquals(s.Native, source) && s.Binding.ThreadId == id.GetString());
        if (session == null) return;
        lock (session.Gate)
        {
            if (parameters.TryGetProperty("turnId", out var eventTurn) && eventTurn.GetString() != session.Turn) return;
            if (message.TryGetProperty("id", out var requestId))
            {
                var nonce = Guid.NewGuid().ToString("N")[..12];
                if (method is "item/commandExecution/requestApproval" or "item/fileChange/requestApproval")
                {
                    var turn = parameters.TryGetProperty("turnId", out var t) ? t.GetString()! : "";
                    var detail = parameters.GetRawText();
                    if (method == "item/fileChange/requestApproval" && parameters.TryGetProperty("itemId", out var itemId) &&
                        session.Items.TryGetValue(itemId.GetString()!, out var item)) detail += "\n" + item.GetRawText();
                    var reviewable = detail.Length <= 1600 && (method != "item/fileChange/requestApproval" || detail.Contains("\"changes\""));
                    approvals[nonce] = new Approval(requestId.Clone(), method, session.Binding.Address, session.Binding.ThreadId, turn, reviewable);
                    session.Bubble.Append("\nNative approval required: " + method + "\n" +
                        (reviewable ? detail + "\n/approve " + nonce + " or " : "Full request requires the native PC review surface; Telegram cannot approve a truncated request.\n") +
                        "/deny " + nonce + "\n");
                }
                else if (method == "item/tool/requestUserInput")
                {
                    var qs = parameters.GetProperty("questions");
                    questions[nonce] = new Question(requestId.Clone(), session.Binding.Address, session.Binding.ThreadId,
                        parameters.GetProperty("turnId").GetString()!, qs.Clone(), new Dictionary<string, object>());
                    foreach (var question in qs.EnumerateArray())
                        session.Bubble.Append("\nQuestion " + question.GetProperty("id").GetString() + ": " + question.GetProperty("question").GetString() +
                            (question.TryGetProperty("options", out var options) && options.ValueKind == JsonValueKind.Array ?
                                "\nOptions: " + string.Join(" / ", options.EnumerateArray().Select(o => o.GetProperty("label").GetString())) : "") +
                            "\n/answer " + nonce + " " + question.GetProperty("id").GetString() + " <your answer>\n");
                }
                else session.Bubble.Append("\nNative request needs adapter support: " + method + ". It has not been automatically approved.\n");
            }
            else if (method == "turn/started")
            {
                var started = parameters.GetProperty("turn").GetProperty("id").GetString();
                if (started == session.Turn) return; // Duplicate start must not resurrect/rotate a completed response.
                if (!session.Busy) { BeginBubble(session); session.Elapsed.Restart(); session.Carried = TimeSpan.Zero; session.DeltaItems.Clear(); session.Items.Clear(); session.CompletedItems.Clear(); session.CompletedOrder.Clear(); }
                session.Turn = started; session.Busy = true; session.Status = "Working";
            }
            else if (method == "turn/completed")
            {
                var turn = parameters.GetProperty("turn");
                if (turn.GetProperty("id").GetString() != session.Turn) return;
                session.Busy = false; session.Status = turn.GetProperty("status").GetString() switch {
                    "completed" => "Done", "interrupted" => "Stopped", _ => "Failed — inspect native session" };
                session.Elapsed.Stop();
                if (turn.TryGetProperty("error", out var failure) && failure.ValueKind == JsonValueKind.Object)
                    session.Bubble.Append("\nNative turn failed: " + failure.GetProperty("message").GetString() + "\n");
                foreach (var entry in approvals.Where(p => p.Value.Thread == session.Binding.ThreadId && p.Value.Turn == session.Turn)) approvals.TryRemove(entry.Key, out _);
                foreach (var entry in questions.Where(p => p.Value.Thread == session.Binding.ThreadId && p.Value.Turn == session.Turn)) questions.TryRemove(entry.Key, out _);
            }
            else if (method == "item/agentMessage/delta")
            {
                if (parameters.TryGetProperty("itemId", out var itemId)) session.DeltaItems.Add(itemId.GetString()!);
                session.Bubble.Append(parameters.GetProperty("delta").GetString()!);
            }
            else if (method == "item/commandExecution/outputDelta") session.Bubble.Append(parameters.GetProperty("delta").GetString()!);
            else if (method == "item/started")
            {
                var item = parameters.GetProperty("item");
                if (item.TryGetProperty("id", out var itemId))
                {
                    if (session.Items.Count > 30) session.Items.Clear();
                    session.Items[itemId.GetString()!] = item.Clone();
                }
                session.Bubble.Append(NativeEventView.Tool(item, completed: false));
            }
            else if (method == "item/completed")
            {
                var item = parameters.GetProperty("item");
                if (item.TryGetProperty("id", out var completedId) && completedId.ValueKind == JsonValueKind.String)
                {
                    var key = completedId.GetString()!;
                    if (!session.CompletedItems.Add(key)) return;
                    session.CompletedOrder.Enqueue(key);
                    // Bounded display deduplication, not action-delivery authority.
                    if (session.CompletedOrder.Count > 2048) session.CompletedItems.Remove(session.CompletedOrder.Dequeue());
                }
                if (item.GetProperty("type").GetString() == "agentMessage" && !session.DeltaItems.Contains(item.GetProperty("id").GetString()!))
                    session.Bubble.Append(item.GetProperty("text").GetString()!);
                else if (item.GetProperty("type").GetString() == "userMessage") session.Bubble.Append(NativeEventView.User(item));
                else session.Bubble.Append(NativeEventView.Tool(item, completed: true));
            }
            else if (method is "thread/goal/updated" or "thread/goal/cleared")
            {
                try { session.Goal.Apply(method == "thread/goal/cleared" ? JsonSerializer.SerializeToElement<object?>(null) : parameters.GetProperty("goal")); }
                catch (Exception error) when (error is InvalidDataException or KeyNotFoundException or InvalidOperationException) { return; }
            }
            Touch(session);
        }
    }

    private async Task EditLoop(CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            foreach (var session in sessions.Values)
            {
                lock (session.Gate)
                {
                    if (session.Claude is { Connected: false } && !session.Held)
                    {
                        session.Held = true; session.Status = "Held — Claude stream disconnected";
                        session.Bubble.Append("\nNative connection ended. Input is not replayed or sent to another session.\n"); Touch(session);
                    }
                }
                await FlushBubble(session, stop);
            }
            await Task.Delay(3000, stop);
        }
    }
    private async Task Menus(CancellationToken stop)
    {
        var common = new[] { ("help", "PC session controls"), ("status", "Exact PC session status"), ("cancel", "Interrupt the active native turn"),
            ("limits", "Read native subscription usage (no paid reset)"),
            ("remote", "Read THIS native process's Remote Control state"),
            ("model", "List or set native model"), ("effort", "Set native reasoning effort"),
            ("approve", "Approve an exact pending native request"), ("deny", "Deny an exact pending native request"), ("answer", "Answer an exact native question") };
        // Configure only activated bindings, not inaccessible migration chats.
        foreach (var chat in sessions.Keys.Select(address => address.Chat).Distinct().Order())
        {
            // Telegram has no per-topic command scope. Use the backend union
            // for this chat; /help and dispatch remain exact-topic specific.
            var commands = sessions.Values.Any(s => s.Binding.Chat == chat && s.Claude == null) ?
                common.Append(("goal", "Get, set, pause, resume or clear the Codex goal")).ToArray() : common;
            var scope = new { type = "chat_member", chat_id = chat, user_id = policy.OwnerId };
            await telegram.Call("setMyCommands", new { scope, commands = commands.Select(c => new { command = c.Item1, description = c.Item2 }) }, stop, effect: true);
            var readback = await telegram.Call("getMyCommands", new { scope }, stop);
            if (!readback.EnumerateArray().Select(c => c.GetProperty("command").GetString()).SequenceEqual(commands.Select(c => c.Item1)))
                throw new InvalidOperationException("Telegram command menu readback differs");
        }
    }
    private void Touch(Session session) { session.Revision++; session.Dirty = true; Persist(session); }
    private static string NativeStateKey(string key, string runtime) => runtime == "windows" ? key : key + "/" + runtime;
    private void Persist(Session session)
    {
        var goal = session.Goal.Snapshot;
        ledger.Put("bubble/" + session.Binding.ThreadId, new {
            chat = session.Binding.Chat, topic = session.Binding.Topic,
            backend = session.Binding.Backend, runtime = session.Binding.Runtime,
            claudeState = session.Claude == null ? null : session.ClaudeState,
            tail = session.Bubble.Tail, message = session.Message, sendUnknown = session.SendUnknown, held = session.Held,
            pendingResponses = session.PendingBubbles.Select(r => new { text = r.Text, message = r.Message, lastRendered = r.LastRendered, sendUnknown = r.SendUnknown }).ToArray(),
            busy = session.Busy, status = session.Status, elapsedMs = (session.Carried + session.Elapsed.Elapsed).TotalMilliseconds,
            goal = goal.Goal, goalKnown = goal.Known, goalObservedAt = goal.ObservedAt });
    }
    private void VerifyThread(JsonElement result, string cwd, string? id = null, string runtime = "windows")
    {
        if (result.GetProperty("cwd").GetString() is not { } actual || !actual.Equals(cwd, runtime == "linux" ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase) ||
            result.GetProperty("approvalPolicy").GetString() != policy.NativeApprovalPolicy || result.GetProperty("approvalsReviewer").GetString() != "user" ||
            result.GetProperty("sandbox").GetProperty("type").GetString() != policy.NativeSandboxType ||
            (id != null && result.GetProperty("thread").GetProperty("id").GetString() != id)) throw new InvalidOperationException("Native identity/workspace/security readback mismatch");
    }
    private void StatusFile() => File.WriteAllText(Path.Combine(policy.StateDirectory, "status.json"), JsonSerializer.Serialize(new {
        host = Environment.MachineName, pcOnly = true, bot = policy.BotUsername, nativePid = rpc.Pid, offset = ledger.Offset,
        unknown = ledger.Unknown, bindings = sessions.Values.Select(s => s.Binding), nativeQuota = quota.Snapshot,
        nativeRemote = remote.Snapshot, nativeLinuxPid = linuxRpc?.Pid, nativeLinuxQuota = linuxQuota.Snapshot,
        nativeLinuxRemote = linuxRemote.Snapshot,
        nativeSessions = sessions.Values.Select(s => new { binding = s.Binding, pid = s.Claude?.Pid ?? s.Native.Pid,
            claudeConnected = s.Claude?.Connected }), at = DateTimeOffset.UtcNow }));
}
