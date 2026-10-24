using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;

namespace KhadangRouter;

// Owner-only PC migration adapter. It does not claim company/role gates or
// replace the prepared WSL authorization/admission/deployment components.
public sealed partial class Router(RouterPolicy policy, Ledger ledger, IBot telegram, INative rpc, IAttachments? attachments = null,
    NativeRemote? nativeRemote = null, IClaudeTopics? claudeTopics = null, INative? linuxRpc = null, IOutboundFiles? outboundFiles = null,
    TimeProvider? deliveryClock = null)
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
        public string ClaudeMessageId = "";
        public int ClaudeMessageSequence;
        public readonly Dictionary<string, JsonElement> ClaudeTools = new();
        public readonly Dictionary<string, string> ClaudeToolStatuses = new();
        public readonly Dictionary<string, string> ClaudeToolCompletions = new();
        public readonly Dictionary<int, ClaudeToolInput> ClaudePartialTools = new();
        public string? ClaudeResultStatus;
        public ClaudeDeliveryHold? DeliveryHold;
        public readonly object Gate = new();
        public readonly SemaphoreSlim Dispatch = new(1, 1);
        public readonly SemaphoreSlim Output = new(1, 1);
        public RollingBubble Bubble = new();
        public Stopwatch Elapsed = new();
        public TimeSpan Carried;
        public string? Turn;
        public long NativeStateRevision;
        public string? RestoreTurn;
        public NativeGoal Goal = new(binding.ThreadId);
        public ResponseMessage Response = new();
        public readonly Queue<ResponseMessage> PendingBubbles = new();
        public readonly Queue<FinalAnswerState> PendingAnswers = new();
        public readonly Queue<FinalAnswerState> PendingFiles = new();
        public int RetainedOutput;
        public bool OutputRetentionLoaded;
        public string? OutputError;
        public DateTimeOffset FileScheduledAt;
        public bool Initializing;
        public bool InitializationOverflow;
        public int InitialEventCharacters;
        public readonly Queue<JsonElement> InitialEvents = new();
        // Native steering replies may be commentary while a goal continues.
        // This is display state only, never authorization to send native input.
        public bool GoalReplyPending;
        public readonly HashSet<string> GoalReplyExcludedItems = new();
        public string LastAnswer = "";
        public int? Message { get => Response.Message; set => Response.Message = value; }
        public bool SendUnknown { get => Response.SendUnknown; set => Response.SendUnknown = value; }
        public string Status = "Ready";
        public bool Busy, Dirty, Held;
        public bool PreserveSavedBubble;
        public long Revision;
        public readonly Dictionary<string, JsonElement> Items = new();
        public readonly HashSet<string> DeltaItems = new();
        public readonly HashSet<string> CompletedItems = new();
        public readonly Queue<string> CompletedOrder = new();
    }
    private readonly ConcurrentDictionary<TopicAddress, Session> sessions = new();
    private readonly ConcurrentDictionary<long, Task> handlers = new();
    private TopicProvisioner? topicProvisioner;
    private readonly object topicProvisionerGate = new();
    private sealed record Approval(JsonElement Id, string Method, TopicAddress Address, string Thread, string Turn, bool CanApprove);
    private readonly ConcurrentDictionary<string, Approval> approvals = new();
    private sealed record Question(JsonElement Id, TopicAddress Address, string Thread, string Turn, JsonElement Questions,
        Dictionary<string, object> Answers);
    private readonly ConcurrentDictionary<string, Question> questions = new();
    private readonly SemaphoreSlim starts = new(1, 1);
    private readonly ConcurrentDictionary<string, IClaudeNative> switchedClaude = new();
    private readonly NativeQuota quota = new();
    private readonly ReceiptTyping receiptTyping = new(telegram);
    private readonly NativeRemote remote = nativeRemote ?? new();
    private readonly NativeQuota linuxQuota = new();
    private readonly NativeRemote linuxRemote = new();
    private readonly IAttachments attachmentStore = attachments ?? new Attachments(policy, ledger, telegram);
    private readonly IOutboundFiles fileStore = outboundFiles ?? new OutboundFiles(policy, linuxRpc);
    private DateTimeOffset lastStart = DateTimeOffset.MinValue;
    private readonly object statusGate = new();
    private DateTimeOffset lastPollAttempt;
    private string? backgroundFailure;
    internal TimeSpan HeartbeatInterval { get; init; } = TimeSpan.FromSeconds(5);

    public async Task Run(CancellationToken stop, bool canary = false)
    {
        var callerStop = stop;
        var transportLost = 0;
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(stop);
        stop = lifetime.Token;
        var ownedClaude = new ConcurrentDictionary<IClaudeNative, byte>(ReferenceEqualityComparer.Instance);
        Task edits = Task.CompletedTask;
        Task typing = Task.CompletedTask;
        Task heartbeat = Task.CompletedTask;
        Task attachmentsOut = Task.CompletedTask;
        Task startup = Task.CompletedTask;
        Task menus = Task.CompletedTask;
        using var attachSlots = new SemaphoreSlim(4, 4);
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
        // Subscribe before attachment: a newly mapped native conversation may
        // already be running. Never miss completion while reading its snapshot.
        foreach (var binding in bindings)
        {
            var source = binding.Runtime == "linux" && binding.Backend == "codex" ? linuxRpc! : rpc;
            sessions[binding.Address] = new Session(binding, source) { Initializing = true };
        }
        rpc.Notification += OnNative;
        if (linuxRpc != null) linuxRpc.Notification += OnLinuxNative;
        startup = Task.WhenAll(bindings.Select(binding => AttachBinding(binding, ownedClaude, attachSlots, stop)));
        if (sessions.Count == 0) await CreateLg(stop);
        edits = Task.Run(() => EditLoop(stop), stop);
        typing = Task.Run(() => TypingLoop(stop), stop);
        heartbeat = Task.Run(() => HeartbeatLoop(stop, () => { Volatile.Write(ref transportLost, 1); lifetime.Cancel(); }), stop);
        attachmentsOut = Task.Run(() => AttachmentLoop(stop), stop);
        menus = Task.Run(() => MenuLoop(stop), stop);
        // A dead output/health task is not a healthy Telegram bridge. Exit the
        // observer through the existing supervisor instead of polling forever.
        foreach (var critical in new[] { edits, typing, heartbeat, attachmentsOut, startup })
            _ = critical.ContinueWith(failed => {
                Volatile.Write(ref backgroundFailure, failed.Exception?.GetBaseException().GetType().Name ?? "TaskFault");
                if (NativeObserverRestartSafe()) lifetime.Cancel();
            }, CancellationToken.None,
                TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
            StatusFile();
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
                if (Volatile.Read(ref backgroundFailure) != null && NativeObserverRestartSafe())
                    throw new IOException("Observer background task stopped; supervised same-session reattachment required");
                JsonElement batch;
                try { lock(statusGate) lastPollAttempt = DateTimeOffset.UtcNow;
                    batch = await telegram.Call("getUpdates", new { offset = ledger.Offset, timeout = 25, limit = 50,
                    allowed_updates = new[] { "message" } }, stop); }
                catch (TelegramFailure error) when (error.Code is 0 or 429)
                {
                    // Poll reads are repeatable. A provider cooldown is not a
                    // reason to retry an unknown send, turn or topic creation.
                    await Task.Delay(TimeSpan.FromSeconds(error.Code == 429 ? Math.Clamp(error.RetryAfter, 1, 60) : 3), stop);
                    continue;
                }
                int newlyReceived = 0;
                foreach (var update in batch.EnumerateArray()) if (ledger.Receive(update.GetProperty("update_id").GetInt64(), update.GetRawText())) newlyReceived++;
                foreach (var item in ledger.Pending())
                {
                    if (!ledger.Claim(item.Id)) continue;
                    var task = Handle(item.Id, item.Payload, stop);
                    handlers[item.Id] = task;
                }
                foreach (var done in handlers.Where(pair => pair.Value.IsCompleted).ToArray()) handlers.TryRemove(done.Key, out _);
                StatusFile();
                if (newlyReceived == 0) await Task.Delay(10, stop); // Bound empty/duplicate-only proxy polls.
            }
        }
        catch (OperationCanceledException) when (Volatile.Read(ref transportLost) == 1 && !callerStop.IsCancellationRequested)
        { throw new IOException("Required native observer disconnected; supervised same-session reattachment required, no replay"); }
        finally
        {
            lifetime.Cancel();
            try { await startup; } catch (OperationCanceledException) { }
            rpc.Notification -= OnNative;
            if (linuxRpc != null) linuxRpc.Notification -= OnLinuxNative;
            foreach (var session in sessions.Values)
                if (session.Claude is { } claude)
                {
                    claude.Notification -= session.ClaudeHandler;
                }
            await Task.WhenAll(ownedClaude.Keys.Select(c => c.DisposeAsync().AsTask()));
            await Task.WhenAll(switchedClaude.Values.Distinct<IClaudeNative>(ReferenceEqualityComparer.Instance).Select(c => c.DisposeAsync().AsTask()));
            try { await Task.WhenAll(handlers.Values.Append(edits).Append(typing).Append(heartbeat).Append(attachmentsOut).Append(menus)); } catch (OperationCanceledException) { }
            await receiptTyping.Drain();
        }
    }

    private static bool StartupRouteFailure(Exception error, CancellationToken stop) => !stop.IsCancellationRequested &&
        error is IOException or InvalidDataException or InvalidOperationException or UnauthorizedAccessException or TimeoutException or JsonException;

    private void HoldStartupRoute(Session session, Exception error)
    {
        session.Held = true; session.Status = "Held — exact native worker unavailable; input not replayed";
        // Availability is not evidence of an interrupted/uncertain native
        // action. Keep the original recovery evidence byte-for-byte so a
        // temporary refusal cannot manufacture a permanent native hold.
        session.PreserveSavedBubble = true; session.Dirty = false;
        ledger.Put("startup-held/" + session.Binding.ThreadId, new { binding = session.Binding,
            errorType = error.GetType().Name, preservesOriginalOutbox = session.PreserveSavedBubble, at = DateTimeOffset.UtcNow });
    }

    private async Task HeartbeatLoop(CancellationToken stop, Action connectionLost)
    {
        var nextReconcile = DateTimeOffset.MinValue;
        while (!stop.IsCancellationRequested)
        {
            await ProbeNativeConnections(stop);
            var restart = CheckNativeConnections();
            StatusFile();
            if (restart) { connectionLost(); return; }
            if (DateTimeOffset.UtcNow >= nextReconcile)
            {
                await Task.WhenAll(sessions.Values.Where(s => s.Binding.Backend == "codex" && !s.Initializing)
                    .Select(s => ReconcileCodexSafely(s, stop)));
                nextReconcile = DateTimeOffset.UtcNow.AddSeconds(30);
            }
            await ReadControllerHandoffs(stop);
            await Task.Delay(HeartbeatInterval, stop);
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
        var preparedStart = false;
        try
        {
            if (!update.TryGetProperty("message", out var message) || !TopicConversationAccess.Allows(policy, ledger, message)) { ledger.Finish(updateId, "denied"); return; }
            if (!policy.TryAddress(message, out var address)) { ledger.Finish(updateId, "denied"); return; }
            if (!sessions.TryGetValue(address, out var session))
            {
                if (address.Topic != 1) await telegram.Send(address.Chat, address.Topic, "This chat/topic has no activated PC session. Migration is pending; no message was sent to a model or another session.", stop);
                ledger.Finish(updateId, "unbound"); return;
            }
            target = session;
            if (session.Initializing)
            {
                ledger.Finish(updateId, "retained-connecting");
                await telegram.Send(address.Chat, address.Topic, "This topic is reconnecting to its existing native session. Your message was retained, not submitted or queued. Please resend when /status shows ready; other ready topics remain available.", stop);
                return;
            }
            // The update is durably claimed and the human/topic authenticated.
            // Pulse before dispatch locks, downloads, quotas or either native
            // backend. Synthetic deployment inputs and service events are quiet.
            if (updateId >= 0 && new[] { "text", "photo", "document", "audio", "video", "voice", "animation", "sticker", "video_note" }
                .Any(key => message.TryGetProperty(key, out _))) receiptTyping.Observe(address, stop);
            if (message.TryGetProperty("text", out var topicText) && topicText.ValueKind == JsonValueKind.String &&
                !new[] { "photo", "document", "audio", "video", "voice", "animation", "sticker", "video_note", "media_group_id" }.Any(key => message.TryGetProperty(key, out _)) &&
                TopicCreateRequest.TryParse(topicText.GetString()!, policy.BotUsername, out var topicRequest))
            {
                if (!policy.OwnerMessage(message) || linuxRpc == null)
                { ledger.Finish(updateId, "denied"); return; }
                target = null; // A provisioning failure must not hold the source conversation.
                TopicProvisioner provisioner;
                lock (topicProvisionerGate) provisioner = topicProvisioner ??= new TopicProvisioner(policy, ledger, telegram, linuxRpc, (binding, _) => {
                    policy.ValidateBindings(ledger.Bindings().Append(binding).ToArray());
                    if (sessions.ContainsKey(binding.Address) || sessions.Values.Any(s => s.Binding.ThreadId == binding.ThreadId))
                        throw new InvalidDataException("Duplicate live binding; no repoint");
                    ledger.Bind(binding);
                    if (!sessions.TryAdd(binding.Address, new Session(binding, linuxRpc)))
                        throw new InvalidDataException("Live topic registration collision");
                    StatusFile(); return Task.CompletedTask;
                });
                TopicCreateResult created;
                await starts.WaitAsync(stop);
                try
                {
                    if (sessions.Values.Count(s => s.Busy || s.Initializing) >= policy.MaximumSessions)
                        throw new InvalidOperationException("Active session cap reached; topic request retained without creation");
                    var wait = lastStart.AddSeconds(policy.StartSpacingSeconds) - DateTimeOffset.UtcNow;
                    if (wait > TimeSpan.Zero) await Task.Delay(wait, stop);
                    created = await provisioner.Create(updateId, message, session.Binding, topicRequest!, stop);
                    if (created.Phase == "ready") lastStart = DateTimeOffset.UtcNow;
                }
                catch (Exception error) when (error is not OperationCanceledException)
                {
                    ledger.Finish(updateId, "topic-held-no-replay");
                    var retained = ledger.Get("topic-create/" + address.Chat + "/" + updateId);
                    var phase = retained?.GetProperty("phase").GetString() ?? "preflight";
                    await telegram.Send(address.Chat, address.Topic, "Topic request stopped at " + phase + " (" + error.GetType().Name +
                        "). Request " + updateId + " is retained; no uncertain creation was retried. Existing topics were not restarted or repointed.", stop);
                    return;
                }
                finally { starts.Release(); }
                ledger.Finish(updateId, "topic-ready");
                await telegram.Send(address.Chat, address.Topic, created.Binding.Name + " ready · Codex " + created.Model +
                    " · " + (created.ElapsedMs / 1000).ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + "s\n" + created.Link, stop);
                return;
            }
            if (session.Claude is UnavailableClaude || session.PreserveSavedBubble)
            {
                ledger.Finish(updateId, "held-no-replay");
                await telegram.Send(address.Chat, address.Topic,
                    "This exact topic is held for native recovery. Your message is retained, not sent to another session or replayed. Other healthy topics remain available.", stop);
                return;
            }
            if (message.TryGetProperty("text", out var modelText) && modelText.ValueKind == JsonValueKind.String &&
                !new[] { "photo", "document", "audio", "video", "voice", "animation", "sticker", "video_note", "media_group_id" }.Any(key => message.TryGetProperty(key, out _)) &&
                ModelCommand.TryParse(modelText.GetString()!, policy.BotUsername, out var requestedModel))
            {
                await session.Dispatch.WaitAsync(stop);
                try { RequireCurrent(session); await SwitchModel(session, requestedModel, stop,
                    modelText.GetString()!.TrimStart().StartsWith("cc", StringComparison.OrdinalIgnoreCase) ||
                    modelText.GetString()!.TrimStart().StartsWith("/cc", StringComparison.OrdinalIgnoreCase)); ledger.Finish(updateId, "control"); return; }
                finally { session.Dispatch.Release(); }
            }
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
                try { RequireCurrent(session); await Control(session, text, stop); ledger.Finish(updateId, "control"); return; }
                finally { session.Dispatch.Release(); }
            }
            using var inputScope = ledger.TrackInput(updateId, session.Binding);
            string? mediaTurn = null;
            IReadOnlyList<StagedAttachment> files = [];
            if (references.Count > 0)
            {
                lock (session.Gate)
                {
                    if (session.Held || ledger.InputUnknown(session.Binding) != 0 || session.Busy && session.Turn == null)
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
                RequireCurrent(session);
                string? active;
                lock (session.Gate)
                {
                    if (ledger.InputUnknown(session.Binding) != 0) throw new AttachmentFailure("Uncertain prior effect in this conversation; input retained before native dispatch");
                    if (session.Held) throw new InvalidOperationException("Uncertain prior effect; input held for reconciliation");
                    active = session.Busy ? session.Turn : null;
                    if (mediaTurn != null && active != mediaTurn) throw new AttachmentFailure("Active turn ended or changed during attachment download; staged files held, no fresh-turn fallback");
                    if (session.Busy && active == null) throw new InvalidOperationException("Native turn identity not yet confirmed; no queue fallback");
                }
                var input = Attachments.Input(message.GetProperty("from").GetProperty("id").GetInt64(), message.GetProperty("message_id").GetInt64(), text, files, session.Binding.Runtime);
                if (active != null)
                {
                    var receipt = await session.Native.Call("turn/steer", new { threadId = session.Binding.ThreadId, expectedTurnId = active, input }, stop);
                    NativeEventView.VerifySteer(receipt, active);
                    lock (session.Gate) Touch(session);
                }
                else
                {
                    await starts.WaitAsync(stop);
                    try
                    {
                        if (sessions.Values.Count(s => s.Busy || s.Initializing) >= policy.MaximumSessions) throw new CapacityDenied(policy.MaximumSessions);
                        var wait = lastStart.AddSeconds(policy.StartSpacingSeconds) - DateTimeOffset.UtcNow;
                        if (wait > TimeSpan.Zero) await Task.Delay(wait, stop);
                        lock (session.Gate)
                        {
                            preparedStart = true;
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
        catch (CapacityDenied error)
        {
            // Capacity is checked before a native start/UI reservation. Keep
            // the original input out of the dispatch queue, without holding
            // the topic or changing existing work/approvals/uncertain receipts.
            ledger.Finish(updateId, "retained-capacity");
            if (target != null)
            {
                var notice = "System busy: all " + error.Maximum + " active-session slots are occupied. Input " + updateId +
                    " was retained but NOT sent to the agent. Nothing is queued or replayed automatically. Please resend when a slot is free. /status remains available.";
                ledger.Put("capacity-retained/" + updateId, new { target.Binding, maximum = error.Maximum, nativeSubmitted = false, at = DateTimeOffset.UtcNow });
                lock (target.Gate) { target.Bubble.Append("\n" + notice + "\n"); Touch(target); }
                try { await telegram.Send(target.Binding.Chat, target.Binding.Topic, notice, stop); }
                catch (TelegramFailure failure)
                { ledger.Put("capacity-notice/" + updateId, new { code = failure.Code, retry = false, at = DateTimeOffset.UtcNow }); }
            }
        }
        catch (AttachmentFailure error)
        {
            // Known pre-native failure, not an ambiguous model action. Preserve
            // the current turn/goal and keep subsequent owner inputs usable.
            ledger.Finish(updateId, "held-media");
            if (target != null) lock (target.Gate) { target.Bubble.Append("\nAttachment input " + updateId + " held: " + error.Message + "\n"); Touch(target); }
        }
        catch (NativeNotSubmitted)
        {
            // NativeRpc proved no intent/write happened. Retain the input, but
            // do not poison a healthy conversation with an ambiguous-action
            // hold. The health loop exits this observer for the existing SCM
            // supervisor; no input is retried by this or the next generation.
            ledger.Finish(updateId, "retained-unsubmitted");
            if (target != null)
            {
                ledger.Put("native/unsubmitted/" + updateId, new { target.Binding, reason = "connection-unavailable-before-dispatch", at = DateTimeOffset.UtcNow });
                lock (target.Gate)
                {
                    // Undo only our unsubmitted start's UI reservation. A
                    // busy-with-no-ID placeholder must not become a crash hold
                    // on the next generation. Existing work/holds stay intact.
                    if (preparedStart && target.Turn == null && !target.Held)
                    { target.Busy = false; target.Elapsed.Stop(); target.Status = "Reconnecting — input not sent"; }
                    target.Bubble.Append("\nInput " + updateId + " retained before sending: native connection is recovering. It will not be replayed automatically.\n"); Touch(target);
                }
            }
        }
        catch (Exception error) when (error is not OperationCanceledException)
        {
            ledger.Finish(updateId, error is NativeRejected ? "rejected" : "held-no-replay");
            if (target != null)
                lock (target.Gate)
                {
                    if (error is ClaudeDeliveryTimeout late && late.Session == target.Binding.ThreadId)
                    {
                        target.DeliveryHold = new(late.Operation, late.Uuid, updateId);
                        if (ClaudeDelivery.Confirmed(ledger, late.Operation, late.Session, late.Uuid))
                        {
                            ledger.Exec("UPDATE updates SET status='accepted-late' WHERE id=? AND status='held-no-replay'", updateId);
                            target.DeliveryHold = null; Touch(target); return;
                        }
                    }
                    else target.DeliveryHold = null;
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
                (session.Held ? "Held — reconcile native/transport receipts before continuing." : session.Busy ? "Working; new messages steer this turn." : "Idle.") + "\nInput-blocking unknowns here: " + ledger.InputUnknown(session.Binding) + "\nUnknown operations across relay: " + ledger.Unknown; break;
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
        if (command.Action is "set" or "resume" && (session.Held || ledger.InputUnknown(session.Binding) != 0))
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

    private void OnNative(JsonElement message) => ObserveCodexSafely(rpc, message);
    private void OnLinuxNative(JsonElement message) => ObserveCodexSafely(linuxRpc!, message);
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
        var session = sessions.Values.FirstOrDefault(s => s.Binding.Backend == "codex" && ReferenceEquals(s.Native, source) && s.Binding.ThreadId == id.GetString());
        if (session == null) return;
        lock (session.Gate)
        {
            if (session.Initializing)
            {
                var characters = message.GetRawText().Length;
                if (!session.InitializationOverflow && session.InitialEvents.Count < 512 && session.InitialEventCharacters + (long)characters <= 1_048_576)
                { session.InitialEvents.Enqueue(message.Clone()); session.InitialEventCharacters += characters; }
                else session.InitializationOverflow = true;
                return;
            }
            if (method is "turn/started" or "turn/completed") session.NativeStateRevision++;
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
                        session.Bubble.Upsert("question:" + nonce + ":" + question.GetProperty("id").GetString(), "\nQuestion " + question.GetProperty("id").GetString() + ": " + question.GetProperty("question").GetString() +
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
                if (session.RestoreTurn != null && started != session.RestoreTurn)
                {
                    if (session.Held || session.SendUnknown || ledger.InputUnknown(session.Binding) != 0 ||
                        approvals.Values.Any(a => a.Thread == session.Binding.ThreadId) || questions.Values.Any(q => q.Thread == session.Binding.ThreadId) ||
                        session.Response.Answer.Unknown || session.PendingAnswers.Any(a => a.Unknown) ||
                        session.PendingBubbles.Any(r => r.SendUnknown || r.Answer.Unknown))
                    { session.Held = true; session.Status = "Held — reconcile native/transport receipts"; session.RestoreTurn = null; Touch(session); return; }
                    session.RestoreTurn = null; session.Busy = false;
                    session.Status = "Detached — native work advanced while bridge was offline";
                }
                if (!session.Busy) { BeginBubble(session); session.Elapsed.Restart(); session.Carried = TimeSpan.Zero; session.DeltaItems.Clear(); session.Items.Clear(); session.CompletedItems.Clear(); session.CompletedOrder.Clear(); }
                session.Turn = started; session.Busy = true; session.Status = "Working";
                session.GoalReplyPending = false; session.GoalReplyExcludedItems.Clear();
            }
            else if (method == "turn/completed")
            {
                var turn = parameters.GetProperty("turn");
                if (turn.GetProperty("id").GetString() != session.Turn) return;
                session.RestoreTurn = null;
                session.Busy = false; session.Status = turn.GetProperty("status").GetString() switch {
                    "completed" => "Done", "interrupted" => "Stopped", _ => "Failed — inspect native session" };
                session.Elapsed.Stop();
                session.GoalReplyPending = false; session.GoalReplyExcludedItems.Clear();
                if (turn.GetProperty("status").GetString() == "completed") CompleteAnswer(session);
                session.Bubble.Remove("question:");
                if (turn.TryGetProperty("error", out var failure) && failure.ValueKind == JsonValueKind.Object)
                    session.Bubble.Append("\nNative turn failed: " + failure.GetProperty("message").GetString() + "\n");
                foreach (var entry in approvals.Where(p => p.Value.Thread == session.Binding.ThreadId && p.Value.Turn == session.Turn)) approvals.TryRemove(entry.Key, out _);
                foreach (var entry in questions.Where(p => p.Value.Thread == session.Binding.ThreadId && p.Value.Turn == session.Turn)) questions.TryRemove(entry.Key, out _);
            }
            else if (method == "item/agentMessage/delta")
            {
                if (parameters.TryGetProperty("itemId", out var itemId))
                {
                    session.DeltaItems.Add(itemId.GetString()!);
                    session.Bubble.Upsert("agent:" + itemId.GetString(), parameters.GetProperty("delta").GetString()!, delta: true);
                }
                else session.Bubble.Append(parameters.GetProperty("delta").GetString()!);
            }
            else if (method == "item/commandExecution/outputDelta") return; // Raw output stays in native history, never the phone bubble.
            else if (method == "item/started")
            {
                var item = parameters.GetProperty("item");
                if (item.TryGetProperty("id", out var itemId))
                {
                    if (session.CompletedItems.Contains(itemId.GetString()!)) return;
                    if (session.Items.Count > 30) session.Items.Clear();
                    session.Items[itemId.GetString()!] = item.Clone();
                }
                var label = NativeEventView.Tool(item, completed: false);
                if (label.Length > 0 && item.TryGetProperty("id", out var toolId)) session.Bubble.Upsert("tool:" + toolId.GetString(), label, important: NativeEventView.Failed(item));
            }
            else if (method == "item/completed")
            {
                var item = parameters.GetProperty("item");
                if (item.TryGetProperty("id", out var completedId) && completedId.ValueKind == JsonValueKind.String)
                {
                    var key = completedId.GetString()!;
                    if (!session.CompletedItems.Add(key)) return;
                    session.DeltaItems.Remove(key); // Keep only currently streaming messages, not an entire long goal.
                    session.CompletedOrder.Enqueue(key);
                    // Bounded display deduplication, not action-delivery authority.
                    if (session.CompletedOrder.Count > 2048) session.CompletedItems.Remove(session.CompletedOrder.Dequeue());
                }
                if (item.GetProperty("type").GetString() == "agentMessage")
                {
                    var text = item.GetProperty("text").GetString()!;
                    session.Bubble.Upsert("agent:" + item.GetProperty("id").GetString(), text);
                    var phase = item.TryGetProperty("phase", out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;
                    if (phase != "commentary") ConsiderAnswer(session, text, phase == "final_answer");
                    var directReply = session.GoalReplyPending && !string.IsNullOrWhiteSpace(text) &&
                        !session.GoalReplyExcludedItems.Contains(item.GetProperty("id").GetString()!);
                    if (directReply && phase == "commentary")
                    {
                        // Do not wait for turn/completed: a goal can keep the
                        // same turn open long after answering a human message.
                        var answer = new FinalAnswerState();
                        try { answer.Consider(text, authoritative: true); answer.Complete(); session.PendingAnswers.Enqueue(answer); session.LastAnswer = RollingBubble.SafeTail(text, 12000); }
                        catch (InvalidDataException) { session.Held = true; session.Bubble.Append("Reply delivery held: text exceeds the delivery bound; native history retained."); }
                    }
                    if (directReply) { session.GoalReplyPending = false; session.GoalReplyExcludedItems.Clear(); }
                    // A goal can continue the same native turn after an actual
                    // final answer. Deliver that answer now, not at goal end.
                    if (phase == "final_answer" && (directReply || session.Goal.Value?.GetProperty("status").GetString() == "active"))
                    {
                        CompleteAnswer(session);
                        session.PendingAnswers.Enqueue(session.Response.Answer);
                        session.Response.Answer = new();
                    }
                }
                else if (item.GetProperty("type").GetString() == "userMessage")
                {
                    session.Bubble.Append(NativeEventView.User(item));
                    if (session.Goal.Value?.GetProperty("status").GetString() == "active" && NativeEventView.DirectInput(item))
                    {
                        session.GoalReplyPending = true;
                        session.GoalReplyExcludedItems.Clear();
                        // Already-streaming prose cannot answer input received
                        // later. Wait for the next completed assistant message.
                        foreach (var excludedId in session.DeltaItems.Concat(session.Items.Where(p =>
                            p.Value.TryGetProperty("type", out var kind) && kind.GetString() == "agentMessage").Select(p => p.Key))
                            .Where(id => !session.CompletedItems.Contains(id)).Distinct().Take(32))
                            session.GoalReplyExcludedItems.Add(excludedId);
                    }
                }
                else
                {
                    var displayItem = item;
                    if (item.TryGetProperty("id", out var displayId) && session.Items.TryGetValue(displayId.GetString()!, out var started))
                    {
                        var fields = started.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone());
                        foreach (var field in item.EnumerateObject()) fields[field.Name] = field.Value.Clone();
                        displayItem = JsonSerializer.SerializeToElement(fields);
                    }
                    var label = NativeEventView.Tool(displayItem, completed: true);
                    if (label.Length > 0 && item.TryGetProperty("id", out var toolId)) session.Bubble.Upsert("tool:" + toolId.GetString(), label, important: NativeEventView.Failed(displayItem));
                }
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
        var actors = new Dictionary<TopicAddress, (Session Session, CancellationTokenSource Stop, Task Task)>();
        try
        {
            while (!stop.IsCancellationRequested)
            {
                foreach (var session in sessions.Values)
                {
                    var address = session.Binding.Address;
                    if (actors.TryGetValue(address, out var old) && !ReferenceEquals(old.Session, session))
                    {
                        old.Stop.Cancel();
                        try { await old.Task; } catch (OperationCanceledException) { }
                        old.Stop.Dispose(); actors.Remove(address);
                    }
                    if (!actors.ContainsKey(address))
                    {
                        var token = CancellationTokenSource.CreateLinkedTokenSource(stop);
                        actors.Add(address, (session, token, TextLoop(session, token.Token)));
                    }
                }
                await Task.Delay(250, stop);
            }
        }
        finally
        {
            try { await Task.WhenAll(actors.Values.Select(a => a.Task)); }
            finally { foreach (var actor in actors.Values) actor.Stop.Dispose(); }
        }
    }
    private async Task TextLoop(Session session, CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            if (session.Initializing) { await Task.Delay(250, stop); continue; }
            try
            {
                lock (session.Gate)
                {
                    ReleaseClaudeDeliveryHold(session);
                    if (session.Claude is { Connected: false } && !session.Held)
                    {
                        session.Held = true; session.Status = "Held — Claude stream disconnected";
                        session.Bubble.Append("\nNative connection ended. Input is not replayed or sent to another session.\n"); Touch(session);
                    }
                }
                await FlushBubble(session, stop);
            }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { throw; }
            catch (Exception error)
            {
                RecordOutputFault(session, "text", error);
            }
            await Task.Delay(3000, stop);
        }
    }
    private void RefreshTyping(CancellationToken stop)
    {
        foreach (var session in sessions.Values)
        {
            bool working;
            lock (session.Gate) working = session.Busy && !session.Held && session.Status == "Working" &&
                session.Claude is not { Connected: false };
            receiptTyping.Refresh(session.Binding.Address, working, stop);
        }
    }
    private async Task TypingLoop(CancellationToken stop)
    {
        // Independent of slow bubble edits/final sends and native dispatch.
        // One-second burst coalescing plus a two-second tick renews within the
        // Telegram five-second lifetime, without an always-on idle indicator.
        while (!stop.IsCancellationRequested)
        {
            RefreshTyping(stop);
            await Task.Delay(2000, stop);
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
            var commands = sessions.Values.Any(s => s.Binding.Chat == chat && s.Binding.Backend == "codex") ?
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
        if (session.PreserveSavedBubble || session.Initializing) return;
        var goal = session.Goal.Snapshot;
        ledger.Put("bubble/" + session.Binding.ThreadId, new {
            chat = session.Binding.Chat, topic = session.Binding.Topic,
            backend = session.Binding.Backend, runtime = session.Binding.Runtime,
            claudeState = session.Claude == null ? null : session.ClaudeState,
            tail = session.Bubble.Tail, message = session.Message, sendUnknown = session.SendUnknown, held = session.Held,
            claudeDeliveryHold = session.DeliveryHold, progressRetained = session.Response.ProgressRetained,
            pendingResponses = session.PendingBubbles.Select(r => new { text = r.Text, message = r.Message, lastRendered = r.LastRendered, sendUnknown = r.SendUnknown, progressSuperseded = r.ProgressSuperseded, progressRetained = r.ProgressRetained, finalAnswer = r.Answer }).ToArray(),
            pendingAnswers = session.PendingAnswers.ToArray(),
            pendingFiles = session.PendingFiles.ToArray(), retainedOutput = session.RetainedOutput, outputError = session.OutputError,
            goalReplyPending = session.GoalReplyPending, goalReplyExcludedItems = session.GoalReplyExcludedItems.ToArray(),
            completedItems = session.CompletedOrder.ToArray(),
            finalAnswer = session.Response.Answer,
            outputRateLimited = false, // Legacy daily budgets are audit only; no application daily limit.
            lastAnswer = session.LastAnswer,
            busy = session.Busy, status = DisplayStatus(session), nativeStatus = session.Status, elapsedMs = (session.Carried + session.Elapsed.Elapsed).TotalMilliseconds,
            turn = session.Turn,
            goal = goal.Goal, goalKnown = goal.Known, goalObservedAt = goal.ObservedAt });
    }
    private void VerifyThread(JsonElement result, string cwd, string? id = null, string runtime = "windows")
    {
        if (result.GetProperty("cwd").GetString() is not { } actual || !actual.Equals(cwd, runtime == "linux" ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase) ||
            result.GetProperty("approvalPolicy").GetString() != policy.NativeApprovalPolicy || result.GetProperty("approvalsReviewer").GetString() != "user" ||
            result.GetProperty("sandbox").GetProperty("type").GetString() != policy.NativeSandboxType ||
            (id != null && result.GetProperty("thread").GetProperty("id").GetString() != id)) throw new InvalidOperationException("Native identity/workspace/security readback mismatch");
    }
    private void StatusFile()
    { lock(statusGate) File.WriteAllText(Path.Combine(policy.StateDirectory, "status.json"), JsonSerializer.Serialize(new {
        host = Environment.MachineName, pcOnly = true, bot = policy.BotUsername, nativePid = rpc.Pid, nativeConnected = Connection(rpc), nativeLastRoundTrip = (rpc as NativeRpc)?.LastRoundTripAt, offset = ledger.Offset,
        nativeTransportHealthy = !sessions.Values.Any(s => s.Claude == null && Connection(s.Native) == false),
        nativeObserverRestartSafe = NativeObserverRestartSafe(),
        backgroundHealthy = Volatile.Read(ref backgroundFailure) == null,
        unknown = ledger.Unknown, presentationUnknown = ledger.PresentationUnknown, receiptTyping = receiptTyping.Snapshot,
        bindings = sessions.Values.Select(s => s.Binding), nativeQuota = quota.Snapshot,
        nativeRemote = remote.Snapshot, nativeLinuxPid = linuxRpc?.Pid, nativeLinuxConnected = Connection(linuxRpc), nativeLinuxLastRoundTrip = (linuxRpc as NativeRpc)?.LastRoundTripAt, nativeLinuxQuota = linuxQuota.Snapshot,
        nativeLinuxRemote = linuxRemote.Snapshot,
        heldSessions = sessions.Values.Count(s => s.Held),
        nativeSessions = sessions.Values.Select(s => new { binding = s.Binding, pid = s.Claude?.Pid ?? s.Native.Pid,
            claudeConnected = s.Claude?.Connected, nativeConnected = s.Claude?.Connected ?? Connection(s.Native), held = s.Held, busy = s.Busy, status = DisplayStatus(s), turn = s.Turn,
            ready = !s.Initializing, admission = ledger.Admission(s.Binding), retainedOutput = s.RetainedOutput, pendingFileBatches = s.PendingFiles.Count, outputError = s.OutputError }),
        lastPollAttempt, at = DateTimeOffset.UtcNow })); }
}
