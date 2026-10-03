using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;

namespace KhadangRouter;

// Owner-only Windows migration adapter. It does not claim company/role gates or
// replace the prepared WSL authorization/admission/deployment components.
public sealed class Router(RouterPolicy policy, Ledger ledger, IBot telegram, INative rpc)
{
    private sealed class Session(Binding binding)
    {
        public Binding Binding { get; } = binding;
        public readonly object Gate = new();
        public readonly SemaphoreSlim Dispatch = new(1, 1);
        public RollingBubble Bubble = new();
        public Stopwatch Elapsed = new();
        public TimeSpan Carried;
        public string? Turn, Goal;
        public int? Message;
        public string LastRendered = "", Status = "Working";
        public bool Busy, SendUnknown, Dirty, Held;
        public long Revision;
        public readonly Dictionary<string, JsonElement> Items = new();
        public readonly HashSet<string> DeltaItems = new();
    }
    private readonly ConcurrentDictionary<int, Session> sessions = new();
    private readonly ConcurrentDictionary<long, Task> handlers = new();
    private sealed record Approval(JsonElement Id, string Method, int Topic, string Thread, string Turn, bool CanApprove);
    private readonly ConcurrentDictionary<string, Approval> approvals = new();
    private sealed record Question(JsonElement Id, int Topic, string Thread, string Turn, JsonElement Questions,
        Dictionary<string, object> Answers);
    private readonly ConcurrentDictionary<string, Question> questions = new();
    private readonly SemaphoreSlim starts = new(1, 1);
    private DateTimeOffset lastStart = DateTimeOffset.MinValue;

    public async Task Run(CancellationToken stop, bool canary = false)
    {
        foreach (var binding in ledger.Bindings())
        {
            policy.Workspace(binding.Workspace);
            if (binding.Chat != policy.ChatId) throw new InvalidDataException("Foreign chat in PC registry");
            var resumed = await rpc.Call("thread/resume", new { threadId = binding.ThreadId, cwd = binding.Workspace,
                approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", permissions = policy.NativePermissionProfile }, stop);
            VerifyThread(resumed, binding.Workspace, binding.ThreadId);
            var session = new Session(binding);
            if (ledger.Get("bubble/" + binding.ThreadId) is { } saved)
            {
                session.Bubble.Append(saved.GetProperty("tail").GetString()!);
                session.Message = saved.GetProperty("message").ValueKind == JsonValueKind.Number ? saved.GetProperty("message").GetInt32() : null;
                session.SendUnknown = saved.GetProperty("sendUnknown").GetBoolean();
                session.Held = saved.GetProperty("held").GetBoolean() || saved.GetProperty("busy").GetBoolean();
                session.Status = session.Held ? "Held — reconcile interrupted turn" : saved.GetProperty("status").GetString()!;
                session.Carried = TimeSpan.FromMilliseconds(saved.GetProperty("elapsedMs").GetDouble());
                session.Dirty = true;
            }
            sessions[binding.Topic] = session;
        }
        rpc.Notification += OnNative;
        if (sessions.Count == 0) await CreateLg(stop);
        var edits = Task.Run(() => EditLoop(stop), stop);
        try
        {
            await Menus(stop);
            if (canary && ledger.Get("native-canary") == null)
            {
                ledger.Put("native-canary", new { state = "attempting", at = DateTimeOffset.UtcNow });
                var sample = JsonSerializer.SerializeToElement(new { message = new { from = new { id = policy.OwnerId, is_bot = false },
                    chat = new { id = policy.ChatId, is_forum = true }, message_thread_id = sessions.Keys.Single(), message_id = 0,
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
            rpc.Notification -= OnNative;
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
            var resumed = await rpc.Call("thread/resume", new { threadId = id, cwd = workspace, approvalPolicy = policy.NativeApprovalPolicy,
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
        ledger.Bind(binding); sessions[topicId] = new Session(binding);
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
            var topic = message.TryGetProperty("message_thread_id", out var t) ? t.GetInt32() : 1;
            if (!sessions.TryGetValue(topic, out var session))
            {
                if (topic != 1) await telegram.Send(policy.ChatId, topic, "This topic has no PC session. Mac Khadang sessions are retired. Use the new LG Magic Remote · PC topic.", stop);
                ledger.Finish(updateId, "unbound"); return;
            }
            target = session;
            if (!message.TryGetProperty("text", out var textElement))
            {
                await telegram.Send(policy.ChatId, topic, "Attachment delivery is not activated in this PC adapter yet. The update is retained in the ledger; it was not silently sent as an empty prompt.", stop);
                ledger.Finish(updateId, "held-media"); return;
            }
            var text = textElement.GetString()!;
            if (text.StartsWith('/'))
            {
                await session.Dispatch.WaitAsync(stop);
                try { await Control(session, text, stop); ledger.Finish(updateId, "control"); return; }
                finally { session.Dispatch.Release(); }
            }
            await session.Dispatch.WaitAsync(stop);
            try
            {
                string? active;
                lock (session.Gate)
                {
                    if (session.Held || ledger.Unknown != 0) throw new InvalidOperationException("Uncertain prior effect; input held for reconciliation");
                    active = session.Busy ? session.Turn : null;
                    if (session.Busy && active == null) throw new InvalidOperationException("Native turn identity not yet confirmed; no queue fallback");
                }
                var input = new[] { new { type = "text", text = "[Telegram owner " + policy.OwnerId + "; message " + message.GetProperty("message_id").GetInt64() + "]\n" + text } };
                if (active != null)
                {
                    await rpc.Call("turn/steer", new { threadId = session.Binding.ThreadId, expectedTurnId = active, input }, stop);
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
                            session.Bubble = new RollingBubble(); session.Elapsed.Restart(); session.Carried = TimeSpan.Zero;
                            session.Status = "Working"; session.Busy = true; session.Turn = null; session.Items.Clear(); session.DeltaItems.Clear(); Touch(session);
                        }
                        var result = await rpc.Call("turn/start", new { threadId = session.Binding.ThreadId, input }, stop);
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
        var parts = text.Split(' ', 2, StringSplitOptions.RemoveEmptyEntries);
        var command = parts[0].Split('@');
        if (command.Length > 1 && !command[1].Equals(policy.BotUsername, StringComparison.OrdinalIgnoreCase)) return;
        var argument = parts.Length > 1 ? parts[1].Trim() : "";
        string answer;
        switch (command[0].ToLowerInvariant())
        {
            case "/help": answer = "PC Codex controls: /status, /cancel, /goal [objective | pause | resume | clear], /model [id], /effort <level>, /approve <nonce>, /deny <nonce>, /answer <nonce> <question-id> <text>. Native Claude routing and attachments are still pending; no Mac fallback is permitted."; break;
            case "/status": answer = "PC session: " + session.Binding.Name + "\nNative thread: " + session.Binding.ThreadId + "\n" +
                (session.Held ? "Held — reconcile native/transport receipts before continuing." : session.Busy ? "Working; new messages steer this turn." : "Idle.") + "\nHeld/unknown operations: " + ledger.Unknown; break;
            case "/cancel":
                string? turn; lock (session.Gate) turn = session.Turn;
                if (turn == null || !session.Busy) { answer = "No active native turn."; break; }
                await rpc.Call("turn/interrupt", new { threadId = session.Binding.ThreadId, turnId = turn }, stop);
                answer = "Interrupt requested; waiting for the native stopped state."; break;
            case "/goal":
                JsonElement goal;
                if (argument == "clear") goal = await rpc.Call("thread/goal/clear", new { threadId = session.Binding.ThreadId }, stop);
                else if (argument is "pause" or "resume") goal = await rpc.Call("thread/goal/set", new { threadId = session.Binding.ThreadId, status = argument == "pause" ? "paused" : "active" }, stop);
                else if (argument.Length > 0) goal = await rpc.Call("thread/goal/set", new { threadId = session.Binding.ThreadId, objective = argument }, stop);
                else goal = await rpc.Call("thread/goal/get", new { threadId = session.Binding.ThreadId }, stop, effect: false);
                if (goal.TryGetProperty("goal", out var g) && g.ValueKind == JsonValueKind.Object)
                {
                    session.Goal = g.GetProperty("objective").GetString() + " [" + g.GetProperty("status").GetString() + "]";
                    answer = "Goal: " + session.Goal + "\nStatus: " + g.GetProperty("status").GetString();
                }
                else { session.Goal = null; answer = "No ongoing goal."; }
                lock (session.Gate) Touch(session); break;
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
                if (!approvals.TryGetValue(argument, out var request) || request.Topic != session.Binding.Topic ||
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
                if (response.Length != 3 || !questions.TryGetValue(response[0], out var question) || question.Topic != session.Binding.Topic ||
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
        await telegram.Send(policy.ChatId, session.Binding.Topic, answer, stop);
    }

    private void OnNative(JsonElement message)
    {
        if (!message.TryGetProperty("method", out var methodElement) || !message.TryGetProperty("params", out var parameters)) return;
        var method = methodElement.GetString()!;
        if (!parameters.TryGetProperty("threadId", out var id)) return;
        var session = sessions.Values.FirstOrDefault(s => s.Binding.ThreadId == id.GetString());
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
                    approvals[nonce] = new Approval(requestId.Clone(), method, session.Binding.Topic, session.Binding.ThreadId, turn, reviewable);
                    session.Bubble.Append("\nNative approval required: " + method + "\n" +
                        (reviewable ? detail + "\n/approve " + nonce + " or " : "Full request requires the native PC review surface; Telegram cannot approve a truncated request.\n") +
                        "/deny " + nonce + "\n");
                }
                else if (method == "item/tool/requestUserInput")
                {
                    var qs = parameters.GetProperty("questions");
                    questions[nonce] = new Question(requestId.Clone(), session.Binding.Topic, session.Binding.ThreadId,
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
                if (!session.Busy) { session.Bubble = new RollingBubble(); session.Elapsed.Restart(); session.Carried = TimeSpan.Zero; session.DeltaItems.Clear(); session.Items.Clear(); }
                session.Turn = parameters.GetProperty("turn").GetProperty("id").GetString(); session.Busy = true; session.Status = "Working";
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
                var item = parameters.GetProperty("item"); var type = item.GetProperty("type").GetString();
                if (item.TryGetProperty("id", out var itemId))
                {
                    if (session.Items.Count > 30) session.Items.Clear();
                    session.Items[itemId.GetString()!] = item.Clone();
                }
                if (type != "agentMessage" && type != "userMessage") session.Bubble.Append("\n⚙ " + type +
                    (item.TryGetProperty("command", out var command) ? ": " + command.ToString() : "") + "\n");
            }
            else if (method == "item/completed")
            {
                var item = parameters.GetProperty("item");
                if (item.GetProperty("type").GetString() == "agentMessage" && !session.DeltaItems.Contains(item.GetProperty("id").GetString()!))
                    session.Bubble.Append(item.GetProperty("text").GetString()!);
            }
            else if (method == "thread/goal/updated" && parameters.TryGetProperty("goal", out var goal))
                session.Goal = goal.ValueKind == JsonValueKind.Object ? goal.GetProperty("objective").GetString() + " [" + goal.GetProperty("status").GetString() + "]" : null;
            Touch(session);
        }
    }

    private async Task EditLoop(CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            foreach (var session in sessions.Values)
            {
                string text; int? message; long revision;
                lock (session.Gate)
                {
                    if (session.SendUnknown || !session.Dirty && !session.Busy) continue;
                    text = session.Bubble.Render(session.Carried + session.Elapsed.Elapsed, session.Goal, session.Status); message = session.Message; revision = session.Revision;
                    if (text == session.LastRendered) continue;
                }
                try
                {
                    if (message == null)
                    {
                        lock (session.Gate) { session.SendUnknown = true; Persist(session); }
                        var sent = await telegram.Send(policy.ChatId, session.Binding.Topic, text, stop);
                        lock (session.Gate) { session.Message = sent.GetProperty("message_id").GetInt32(); session.SendUnknown = false; Persist(session); }
                    }
                    else await telegram.Edit(policy.ChatId, message.Value, text, stop);
                    lock (session.Gate) { session.LastRendered = text; session.Dirty = revision != session.Revision; Persist(session); }
                }
                catch (TelegramFailure failure)
                {
                    if (failure.Code == 429)
                    {
                        lock (session.Gate) { session.SendUnknown = false; Persist(session); }
                        await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(failure.RetryAfter, 1, 60)), stop);
                    }
                    else if (failure.NotModified) lock (session.Gate) { session.LastRendered = text; session.Dirty = revision != session.Revision; Persist(session); }
                    else lock (session.Gate) { session.SendUnknown = true; Persist(session); } // No second bubble after an uncertain first send.
                }
            }
            await Task.Delay(3000, stop);
        }
    }
    private async Task Menus(CancellationToken stop)
    {
        var scope = new { type = "chat_member", chat_id = policy.ChatId, user_id = policy.OwnerId };
        var commands = new[] { ("help", "PC session controls"), ("status", "Exact PC session status"), ("cancel", "Interrupt the active native turn"),
            ("goal", "Get, set, pause, resume or clear the native goal"), ("model", "List or set native model"), ("effort", "Set native reasoning effort"),
            ("approve", "Approve an exact pending native request"), ("deny", "Deny an exact pending native request"), ("answer", "Answer an exact native question") };
        await telegram.Call("setMyCommands", new { scope, commands = commands.Select(c => new { command = c.Item1, description = c.Item2 }) }, stop, effect: true);
        var readback = await telegram.Call("getMyCommands", new { scope }, stop);
        if (!readback.EnumerateArray().Select(c => c.GetProperty("command").GetString()).SequenceEqual(commands.Select(c => c.Item1)))
            throw new InvalidOperationException("Telegram command menu readback differs");
    }
    private void Touch(Session session) { session.Revision++; session.Dirty = true; Persist(session); }
    private void Persist(Session session) => ledger.Put("bubble/" + session.Binding.ThreadId, new {
        tail = session.Bubble.Tail, message = session.Message, sendUnknown = session.SendUnknown, held = session.Held,
        busy = session.Busy, status = session.Status, elapsedMs = (session.Carried + session.Elapsed.Elapsed).TotalMilliseconds });
    private void VerifyThread(JsonElement result, string cwd, string? id = null)
    {
        if (result.GetProperty("cwd").GetString() is not { } actual || !actual.Equals(cwd, StringComparison.OrdinalIgnoreCase) ||
            result.GetProperty("approvalPolicy").GetString() != policy.NativeApprovalPolicy || result.GetProperty("approvalsReviewer").GetString() != "user" ||
            result.GetProperty("sandbox").GetProperty("type").GetString() != policy.NativeSandboxType ||
            (id != null && result.GetProperty("thread").GetProperty("id").GetString() != id)) throw new InvalidOperationException("Native identity/workspace/security readback mismatch");
    }
    private void StatusFile() => File.WriteAllText(Path.Combine(policy.StateDirectory, "status.json"), JsonSerializer.Serialize(new {
        host = Environment.MachineName, pcOnly = true, bot = policy.BotUsername, nativePid = rpc.Pid, offset = ledger.Offset,
        unknown = ledger.Unknown, bindings = sessions.Values.Select(s => s.Binding), at = DateTimeOffset.UtcNow }));
}
