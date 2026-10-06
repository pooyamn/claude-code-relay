using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Channels;

namespace KhadangRouter;

// Router integration fixtures, not an assertion of Windows owner/ACL, real
// subscription steering, native reset recovery or phone round-trip acceptance.
public static class MixedRoutingTests
{
    private const string Pin = "ea0946bd-52b5-4a3e-97a9-8c4e67ebaa55";
    private const string Pin2 = "d4a466cb-626e-4864-b9dd-46d88d197fe6";
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool ok, string name) { if (!ok) throw new Exception(name); checks++; }
        var directory = Path.Combine(root, "mixed-native-routing"); Directory.CreateDirectory(directory);
        var workspace = OperatingSystem.IsWindows() ? Path.Combine(directory, "workspaces") : "C:\\MixedWorkspaces";
        if (OperatingSystem.IsWindows()) Directory.CreateDirectory(Path.Combine(workspace, "fixture"));
        var policy = template with { WorkspaceRoot = workspace, LinuxWorkspaceRoot = "/Users/pouya/projects", StateDirectory = directory,
            AdditionalChats = [new(-100222222), new(-100333333)], StartSpacingSeconds = 1 };
        var bindings = new[] {
            new Binding(policy.ChatId, 42, "Windows Codex", workspace + "\\fixture", "windows-thread"),
            new Binding(-100222222, 42, "Linux Codex", "/Users/pouya/projects/fixture", "linux-thread", "codex", "linux"),
            new Binding(-100333333, 42, "Linux Claude", "/Users/pouya/projects/fixture", Pin, "claude", "linux"),
            new Binding(-100333333, 43, "Other Claude", "/Users/pouya/projects/fixture", Pin2, "claude", "linux") };
        policy.ValidateBindings(bindings); Check(true, "Explicit mixed runtime registry is admitted without path/backend substitution");
        using (var legacy = new Ledger(Path.Combine(directory, "legacy.db")))
        {
            var b = bindings[0];
            legacy.Exec("INSERT INTO bindings VALUES (?,?,?)", b.Chat, b.Topic, Json(new { b.Chat, b.Topic, b.Name, b.Workspace, b.ThreadId }).GetRawText());
            legacy.Bind(b);
            Check(legacy.Bindings().Single() == b, "Legacy five-field binding retains exact Windows Codex defaults");
            foreach (var changed in new[] { b with { Backend = "claude" }, b with { Runtime = "linux" }, b with { ThreadId = "other" } })
            {
                try { legacy.Bind(changed); throw new Exception("Silent native rebind accepted"); }
                catch (InvalidDataException) { checks++; }
            }
        }
        var file = new StagedAttachment("document", "C:\\Protected\\asset.bin", 3, new string('a', 64), "../untrusted.ps1", "application/octet-stream", false);
        var content = ClaudeInput.Create(1, 2, "CAPTION", [file], "linux");
        Check(ClaudeInput.Create(110123423, 13604, "Test", [], "linux")[0].GetProperty("text").GetString() == "Test", "Claude receives exact plain user text without duplicated delivery metadata");
        Check(content[0].GetProperty("type").GetString() == "text" && content.GetRawText().Contains("/mnt/c/Protected/asset.bin") &&
            content.GetRawText().Contains("CAPTION") && content.GetRawText().Contains("untrusted content"), "Claude file input keeps caption, deterministic Linux path and trust marker");
        var codexInput = Json(Attachments.Input(1, 2, "CAPTION", [file with { Image = true }], "linux"));
        Check(codexInput[1].GetProperty("path").GetString() == "/mnt/c/Protected/asset.bin", "Linux Codex image paths are not Windows localImage paths");
        try { ClaudeInput.Create(1, 2, "CAPTION", [file with { Image = true, Size = 2_000_000 }], "linux"); throw new Exception("Partial oversized image accepted"); }
        catch (AttachmentFailure) { checks++; }
        byte[] imageBytes = [137, 80, 78, 71, 13, 10, 26, 10];
        var image = file with { Image = true, Size = imageBytes.Length, Sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(imageBytes)) };
        var imageBlock = Json(ClaudeInput.ImageBlock(image, imageBytes));
        Check(imageBlock.GetProperty("type").GetString() == "image" && imageBlock.GetProperty("source").GetProperty("media_type").GetString() == "image/png" &&
            imageBlock.GetProperty("source").GetProperty("type").GetString() == "base64", "Claude images use the native image/base64 block, with signature-derived MIME rather than a supplied MIME or localImage");
        try { ClaudeInput.ImageBlock(image with { Sha256 = new string('a', 64) }, imageBytes); throw new Exception("Changed image accepted"); }
        catch (AttachmentFailure) { checks++; }
        Check(!ClaudeInput.Usage(Json(new { rate_limits_available = true, rate_limits = new { five_hour = new { utilization = 17.2 },
            extra_usage = new { secret = "DO-NOT-RENDER" } } })).Contains("DO-NOT-RENDER"), "Usage renderer allowlists plan windows, not raw native settings or spend payloads");
        Check(!ClaudeInput.Reviewable(Json(new { input = new { token = "hidden" } })) &&
            !ClaudeInput.Reviewable(Json(new { input = new { harmlessName = "Bearer hidden-value" } })) &&
            ClaudeInput.Reviewable(Json(new { input = new { path = "fixture.txt" } })), "Approval review checks JSON keys/scalars, not ineffective plain-text redaction of quoted JSON keys");

        foreach (var bad in new[] { "missing-claude", "missing-linux", "wrong-backend", "wrong-runtime", "outside-linux", "duplicate-pin", "aliased-rpc", "receipt-runtime" })
        {
            var path = Path.Combine(directory, bad); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "router.db")); ledger.Bind(bindings[0]);
            ledger.Bind(bad switch {
                "wrong-backend" => bindings[2] with { Backend = "unknown" }, "wrong-runtime" => bindings[2] with { Runtime = "wsl" },
                "outside-linux" => bindings[2] with { Workspace = "/Users/pouya/projectsecret/fixture" },
                "duplicate-pin" => bindings[1] with { ThreadId = bindings[0].ThreadId },
                "missing-linux" or "aliased-rpc" => bindings[1], _ => bindings[2] });
            if (bad == "receipt-runtime") ledger.Put("bubble/" + bindings[2].ThreadId, new { chat = bindings[2].Chat, topic = bindings[2].Topic, runtime = "windows" });
            var win = new Codex(policy); var linux = new Codex(policy); var topics = new Topics(); var bot = new Bot(policy, bindings);
            try { await new Router(policy with { StateDirectory = path }, ledger, bot, win,
                claudeTopics: bad == "missing-claude" ? null : topics, linuxRpc: bad == "missing-linux" ? null : bad == "aliased-rpc" ? win : linux).Run(CancellationToken.None);
                throw new Exception("Bad mixed registry accepted"); }
            catch (InvalidDataException) { Check(win.Calls.Count == 0 && linux.Calls.Count == 0 && topics.Opened.Count == 0 && bot.Menus.Count == 0,
                "Mixed registry/provider preflight precedes ALL native/bot effects: " + bad); }
        }
        foreach (var bad in new[] { "foreign-pin", "initialization-failure" })
        {
            var path = Path.Combine(directory, bad); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "router.db")); ledger.Bind(bindings[2]); ledger.Bind(bindings[3]);
            var topics = new Topics(bad); var win = new Codex(policy); var bot = new Bot(policy, bindings);
            try { await new Router(policy with { StateDirectory = path }, ledger, bot, win, claudeTopics: topics).Run(CancellationToken.None); throw new Exception("Bad Claude startup accepted"); }
            catch (Exception error) when (error is InvalidDataException or IOException)
            { Check(topics.Opened.Count == 2 && topics.Opened.All(c => c.Disposed) && bot.Menus.Count == 0, "Startup failure closes all acquired Claude streams, including the unregistered one: " + bad); }
        }
        foreach (var scenario in new[] { "initialize-race", "initialize-question", "media-race", "slow-usage", "failed-usage", "late-delivery", "ack-timeout-race", "late-unrelated-hold" })
        {
            var path = Path.Combine(directory, scenario); Directory.CreateDirectory(path);
            using var ledger = new Ledger(Path.Combine(path, "router.db")); var b = bindings[2]; ledger.Bind(b);
            var topics = new Topics(scenario, ledger); var win = new Codex(policy); var bot = new Bot(policy, [b]);
            ledger.Put("bubble/" + b.ThreadId, new { chat = b.Chat, topic = b.Topic, tail = "Fixture", message = 900,
                sendUnknown = false, held = false, busy = false, status = "Ready", elapsedMs = 0 });
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(12));
            var run = new Router(policy with { StateDirectory = path }, ledger, bot, win, new MediaRace(topics), claudeTopics: topics).Run(stop.Token);
            try
            {
                await bot.Ready.Task.WaitAsync(stop.Token); var claude = topics.Opened.Single();
                if (scenario == "initialize-race")
                    Check(!ledger.Get("bubble/" + Pin)!.Value.GetProperty("busy").GetBoolean(), "Newer Claude idle notification wins over stale initialize.running reply");
                else if (scenario == "initialize-question")
                    Check(ledger.Get("bubble/" + Pin)!.Value.GetProperty("busy").GetBoolean() && Regex.IsMatch(Tail(ledger), @"/answer [a-f0-9]{12}"),
                        "Pending initialization question survives stale initialize.idle reply and remains human-answerable");
                else if (scenario == "media-race")
                {
                    bot.Post(new { update_id = 1, message = new { from = new { id = policy.OwnerId, is_bot = false }, chat = new { id = b.Chat, is_forum = true },
                        message_thread_id = b.Topic, message_id = 1, caption = "CAPTION", document = new { file_id = "fixture", file_size = 3 } } });
                    await Wait(() => Done(ledger, 1), stop.Token);
                    Check(claude.Inputs.Count == 0 && ledger.Query("SELECT status FROM updates WHERE id=1")[0][0] == "held-media" &&
                        !ledger.Get("bubble/" + Pin)!.Value.GetProperty("held").GetBoolean(), "Changed native work during media staging retains the complete input, without a fresh send or blocking healthy work");
                }
                else if (scenario is "late-delivery" or "ack-timeout-race" or "late-unrelated-hold")
                {
                    bot.Post(bot.Update(1, b, "START")); await Wait(() => Done(ledger, 1), stop.Token);
                    if (scenario != "ack-timeout-race")
                    {
                        Check(ledger.Unknown == 1 && ledger.Get("bubble/" + Pin)!.Value.GetProperty("held").GetBoolean(), "Receipt timeout holds precisely the submitted input");
                        if (scenario == "late-unrelated-hold") claude.Emit(new { type = "system", session_id = Pin, subtype = "worker_shutting_down" });
                        claude.ConfirmLate();
                    }
                    if (scenario == "late-unrelated-hold")
                        Check(ledger.Unknown == 0 && ledger.Get("bubble/" + Pin)!.Value.GetProperty("held").GetBoolean(), "Late delivery cannot clear a different native shutdown hold");
                    else
                    {
                        await Wait(() => !ledger.Get("bubble/" + Pin)!.Value.GetProperty("held").GetBoolean(), stop.Token);
                        Check(ledger.Unknown == 0 && ledger.Query("SELECT status FROM updates WHERE id=1")[0][0] == "accepted-late" && claude.Inputs.Count == 1,
                            "Exact late acknowledgement clears timeout hold without duplicate work: " + scenario);
                        bot.Post(bot.Update(2, b, "NEXT")); await Wait(() => Done(ledger, 2), stop.Token);
                        Check(claude.Inputs.Count == 2 && ledger.Query("SELECT status FROM updates WHERE id=2")[0][0] == "accepted", "Owner can send next message after reconciled receipt");
                    }
                }
                else
                {
                    bot.Post(bot.Update(1, b, "START")); await Wait(() => Done(ledger, 1), stop.Token);
                    bot.Post(bot.Update(2, b, "/limits")); await Wait(() => claude.Controls.Any(c => c.Kind == "get_usage"), stop.Token);
                    bot.Post(bot.Update(3, b, "STEER-WHILE-USAGE-PENDING"), bot.Update(4, b, "/cancel"));
                    await Wait(() => Done(ledger, 3, 4), stop.Token);
                    Check(claude.Inputs.Count == 2 && claude.Controls.Any(c => c.Kind == "interrupt"), "Claude usage observation does not lock out owner input or interrupt: " + scenario);
                    claude.UsageReply.TrySetResult(Json(new { rate_limits_available = false }));
                    await Wait(() => Done(ledger, 2), stop.Token);
                    Check(!ledger.Get("bubble/" + Pin)!.Value.GetProperty("held").GetBoolean() && ledger.Unknown == 0,
                        "Unavailable/read-failed Claude usage does not hold model work or infer extra quota: " + scenario);
                }
            }
            finally { stop.Cancel(); try { await run; } catch (OperationCanceledException) { } }
        }
        using (var ledger = new Ledger(Path.Combine(directory, "router.db")))
        {
            for (var i = 0; i < bindings.Length; i++)
            {
                ledger.Bind(bindings[i]); ledger.Put("bubble/" + bindings[i].ThreadId, new { chat = bindings[i].Chat, topic = bindings[i].Topic,
                    tail = "Fixture", message = 900 + i, sendUnknown = false, held = false, busy = false, status = "Ready", elapsedMs = 0 });
            }
            var win = new Codex(policy); var linux = new Codex(policy); var topics = new Topics(); var bot = new Bot(policy, bindings);
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(25));
            var run = new Router(policy, ledger, bot, win, claudeTopics: topics, linuxRpc: linux).Run(stop.Token);
            try
            {
                await bot.Ready.Task.WaitAsync(stop.Token);
                var claude = topics.Opened.Single(c => c.SessionId == Pin);
                var other = topics.Opened.Single(c => c.SessionId == Pin2);
                var remoteRequest = claude.Controls.Single(c => c.Kind == "remote_control").Args;
                Check(remoteRequest.GetProperty("enabled").GetBoolean() && remoteRequest.GetProperty("keep_session_on_exit").GetBoolean() &&
                    !remoteRequest.TryGetProperty("reattach_session_id", out _) && ledger.Get("claude/remote/" + Pin)!.Value.GetProperty("phase").GetString() == "ready",
                    "Claude startup enrolls its existing owned stream once; no extra native conversation or copied worker secret");
                Check(other.Controls.Count(c => c.Kind == "remote_control") == 1 &&
                    !win.Calls.Any(c => c.Kind == "remote_control") && !linux.Calls.Any(c => c.Kind == "remote_control"),
                    "App enrollment is Claude-only and exact-conversation scoped");
                bot.Post(Enumerable.Range(0, 3).Select(i => bot.Update(100 + i, bindings[i], "START-" + i)).ToArray());
                await Wait(() => Done(ledger, 100, 101, 102), stop.Token);
                Check(win.Starts.Single().GetProperty("threadId").GetString() == bindings[0].ThreadId &&
                    linux.Starts.Single().GetProperty("threadId").GetString() == bindings[1].ThreadId && claude.Inputs.Count == 1 && other.Inputs.Count == 0,
                    "One Telegram poller selects exact Windows Codex, Linux Codex or Claude source for matching topic numbers");
                // Correct ID on the WRONG native source must not route either.
                win.Event("item/agentMessage/delta", new { threadId = bindings[1].ThreadId, turnId = "native-turn", delta = "FOREIGN-SOURCE" });
                linux.Event("item/agentMessage/delta", new { threadId = bindings[0].ThreadId, turnId = "native-turn", delta = "FOREIGN-SOURCE" });
                claude.Emit(new { type = "user", session_id = Pin2, parent_tool_use_id = (string?)null, message = new { content = "FOREIGN-SOURCE" } });
                claude.Emit(new { type = "assistant", session_id = Pin, parent_tool_use_id = "subagent", message = new { content = new[] { new { type = "text", text = "SUBAGENT-PRIVATE" } } } });
                claude.Question("question", Ask()); claude.Question("approval", new { subtype = "can_use_tool", tool_name = "Read", input = new { path = "fixture.txt" } });
                claude.Question("cancelled", new { subtype = "can_use_tool", tool_name = "Read", input = new { path = "cancelled.txt" } });
                var approvalNonces = Regex.Matches(Tail(ledger), @"/approve ([a-f0-9]{12})").Select(m => m.Groups[1].Value).ToArray();
                var q = Regex.Match(Tail(ledger), @"/answer ([a-f0-9]{12})").Groups[1].Value;
                Check(q.Length == 12 && approvalNonces.Length == 2 && claude.Answers.Count == 0, "Native Claude questions are surfaced but never automatically answered/approved");
                claude.Emit(new { type = "control_cancel_request", request_id = "cancelled" });
                claude.Emit(new { type = "control_request", request_id = "unsupported-dialog", request = new { subtype = "request_user_dialog", dialog_kind = "unknown-kind" } });
                claude.Question("question", Ask());
                Check(Regex.Matches(Tail(ledger), @"/answer ([a-f0-9]{12})").Count == 1, "Repeated native Claude request reuses its existing UI receipt");
                bot.Post(bot.Update(110, bindings[0], "/approve " + approvalNonces[0]), bot.Update(111, bindings[1], "/answer " + q + " 1 wrong"),
                    bot.Update(112, bindings[3], "/approve " + approvalNonces[0]), bot.Update(113, bindings[2], "/approve " + q),
                    bot.Update(114, bindings[2], "/approve " + approvalNonces[1]));
                await Wait(() => Done(ledger, 110, 111, 112, 113, 114), stop.Token);
                Check(claude.Answers.Count == 0 && win.Replies == 0 && linux.Replies == 0 && other.Answers.Count == 0,
                    "No cross-chat/backend/topic, cancelled or answerless question approval is forwarded");
                bot.Post(bot.Update(120, bindings[2], "/answer " + q + " 1 A"), bot.Update(121, bindings[2], "/answer " + q + " 2 A, B"),
                    bot.Update(122, bindings[2], "/APPROVE " + approvalNonces[0]), bot.Update(123, bindings[2], "/limits"),
                    bot.Update(124, bindings[2], "/model absent"), bot.Update(125, bindings[2], "/model opus[1m]"),
                    bot.Update(126, bindings[2], "/effort high"), bot.Update(127, bindings[2], "/goal pause"), bot.Update(128, bindings[2], "/clear"));
                await Wait(() => Done(ledger, 120, 121, 122, 123, 124, 125, 126, 127, 128), stop.Token);
                var answers = claude.Answers.Single(a => a.Id == "question").Answer.GetProperty("updatedInput");
                Check(answers.GetProperty("questions").GetArrayLength() == 2 && answers.GetProperty("preserve").GetString() == "original" &&
                    answers.GetProperty("answers").GetProperty("First full question?").GetString() == "A" &&
                    answers.GetProperty("answers").GetProperty("Second full question?").GetString() == "A, B", "Claude answers use exact full-text keys and preserve original native tool input");
                Check(claude.Answers.Single(a => a.Id == "approval").Answer.GetProperty("behavior").GetString() == "allow", "Case-insensitive approval remains an explicit exact-request allow");
                claude.Question("redacted", new { subtype = "can_use_tool", tool_name = "Read", input = new { token = "DO-NOT-PUBLISH" } });
                var redacted = Regex.Matches(Tail(ledger), @"/deny ([a-f0-9]{12})").Last().Groups[1].Value;
                bot.Post(bot.Update(129, bindings[2], "/approve " + redacted)); await Wait(() => Done(ledger, 129), stop.Token);
                Check(claude.Answers.Count == 2 && !Tail(ledger).Contains("DO-NOT-PUBLISH"), "Redacted request is not published or approvable from an incomplete Telegram review");
                bot.Post(bot.Update(131, bindings[2], "/deny " + redacted)); await Wait(() => Done(ledger, 131), stop.Token);
                Check(claude.Answers.Single(a => a.Id == "redacted").Answer.GetProperty("behavior").GetString() == "deny" &&
                    claude.Answers.All(a => a.Id != "unsupported-dialog"), "Owner can deny an exact unreviewable tool request; unknown dialogs are not answered or cancelled");
                Check(claude.Controls.Count(c => c.Kind == "set_model") == 1 && claude.Controls.Single(c => c.Kind == "apply_flag_settings").Args
                    .GetProperty("settings").GetProperty("effortLevel").GetString() == "high" && claude.Controls.Single(c => c.Kind == "get_usage").Args.GetProperty("skip_behaviors").GetBoolean(),
                    "Claude model/effort/usage use its own measured controls, not Codex settings or a transcript scan");
                Check(win.Calls.All(c => !c.Kind.Contains("claude")) && linux.Calls.All(c => !c.Kind.Contains("claude")) && claude.Inputs.Count == 1,
                    "Goal/clear/invalid commands never become prompts or cross-backend RPCs");
                claude.Emit(new { type = "result", session_id = Pin, subtype = "success", result = "Do not duplicate final text" });
                var beforeIdle = ledger.Get("bubble/" + Pin)!.Value;
                Check(beforeIdle.GetProperty("busy").GetBoolean() && beforeIdle.GetProperty("status").GetString() != "Done", "Result alone does not finish Claude work or erase pending authority");
                bot.Post(bot.Update(130, bindings[2], "/cancel")); await Wait(() => Done(ledger, 130), stop.Token);
                Check(claude.Controls.Single(c => c.Kind == "interrupt").Args.GetProperty("cancel_queued").GetBoolean() &&
                    ledger.Get("bubble/" + Pin)!.Value.GetProperty("busy").GetBoolean(), "Interrupt cancels queued native input but ack is not reported as idle");
                bot.Post(bot.Update(140, bindings[0], "STEER-WINDOWS"), bot.Update(141, bindings[1], "STEER-LINUX"), bot.Update(142, bindings[2], "STEER-CLAUDE"));
                await Wait(() => Done(ledger, 140, 141, 142), stop.Token);
                Check(win.Steers.Single().GetProperty("expectedTurnId").GetString() == "native-turn" && linux.Steers.Single().GetProperty("expectedTurnId").GetString() == "native-turn" &&
                    claude.Inputs.Count == 2 && claude.Inputs.All(i => i.Pin == Pin), "Active owner input preserves native steering identities without fabricated Claude turn IDs");
                claude.Emit(new { type = "user", session_id = Pin, uuid = Guid.NewGuid().ToString("D"), parent_tool_use_id = (string?)null, message = new { content = "PHONE-OWNER" } });
                claude.Emit(new { type = "tool_progress", session_id = Pin, tool_name = "Read", tool_use_id = "tool", elapsed_time_seconds = 1 });
                claude.Emit(new { type = "assistant", session_id = Pin, uuid = Guid.NewGuid().ToString("D"), parent_tool_use_id = (string?)null,
                    message = new { content = new[] { new { type = "thinking", thinking = "PRIVATE-THINKING" } } } });
                claude.Emit(new { type = "result", session_id = Pin, subtype = "success" });
                claude.Emit(new { type = "system", session_id = Pin, subtype = "session_state_changed", state = "idle" });
                await Wait(() => bot.Edits.TryGetValue(bindings[2].Address, out var t) && t.Contains("Done (") && t.Contains("PHONE-OWNER") && t.Contains("⏺ Read"), stop.Token);
                await Wait(() => bot.Sends >= 3, stop.Token); // The editor visits independent sessions; one topic's terminal edit is not all-topic delivery.
                Check(bot.Sends >= 3 && bot.MaxPolls == 1 && bot.Edits.Values.All(t => t.Length <= 3900 && !t.Contains("FOREIGN-SOURCE") && !t.Contains("SUBAGENT-PRIVATE") && !t.Contains("PRIVATE-THINKING")),
                    "Each new native response gets a bounded bubble without foreign events, subagent text or thinking; sends=" + bot.Sends + ", polls=" + bot.MaxPolls +
                    ", invalid=" + bot.Edits.Values.Count(t => t.Length > 3900 || t.Contains("FOREIGN-SOURCE") || t.Contains("SUBAGENT-PRIVATE") || t.Contains("PRIVATE-THINKING")));
                Check(!bot.Menus[bindings[2].Chat].EnumerateArray().Any(c => c.GetProperty("command").GetString() == "goal") &&
                    bot.Menus[bindings[0].Chat].EnumerateArray().Any(c => c.GetProperty("command").GetString() == "goal"), "Claude-only chat menu does not advertise Codex goals");
                var next = Guid.NewGuid().ToString("D");
                claude.Emit(new { type = "conversation_reset", session_id = Pin, new_conversation_id = next });
                bot.Post(bot.Update(150, bindings[2], "DO-NOT-SEND-OLD-PIN")); await Wait(() => Done(ledger, 150), stop.Token);
                Check(claude.Inputs.Count == 2 && ledger.Get("claude/reset/" + Pin)!.Value.GetProperty("next").GetString() == next &&
                    ledger.Bindings().Single(b => b.ThreadId == Pin).ThreadId == Pin, "Phone/native reset durably holds old pin; no guessed new-session binding or replay");
            }
            finally { stop.Cancel(); try { await run; } catch (OperationCanceledException) { } }
            Check(topics.Opened.All(c => c.Disposed), "Normal shutdown releases every acquired Claude stream");
        }
        var receipt = Json(new { bridge_session_id = "session_fixture", session_url = "https://claude.ai/code/session_fixture" });
        Check(ClaudeRemoteControl.Parse(receipt).BridgeSessionId == "session_fixture", "Native Remote Control identity and first-party URL are required");
        foreach(var invalidUrl in new[] { "http://claude.ai/code/session_fixture", "https://claude.ai.evil.test/code/session_fixture", "https://user@claude.ai/code/session_fixture", "https://claude.ai/settings", "https://claude.ai/code/", "https://claude.ai:8443/code/session_fixture", "https://claude.ai/code/session_fixture#secret" })
        {
            try { ClaudeRemoteControl.Parse(Json(new { bridge_session_id = "session_fixture", session_url = invalidUrl })); throw new Exception("Unsafe remote URL accepted"); }
            catch(InvalidDataException) { checks++; }
        }
        var remoteDirectory=Path.Combine(directory,"remote-recovery");Directory.CreateDirectory(remoteDirectory);
        using(var ledger=new Ledger(Path.Combine(remoteDirectory,"router.db")))
        {
            var native=new Claude(Pin);var binding=bindings[2];
            await ClaudeRemoteControl.Enable(native,binding,ledger,CancellationToken.None);
            await ClaudeRemoteControl.Enable(native,binding,ledger,CancellationToken.None);
            Check(native.Controls.Single(c=>c.Args.TryGetProperty("reattach_session_id",out _)).Args.GetProperty("reattach_session_id").GetString()=="session_fixture" &&
                native.Inputs.Count==0,"Confirmed cloud mapping is reattached without native prompts, resets or replacement workers");
            ledger.Put("claude/remote/"+Pin,new{phase="attempting"});var count=native.Controls.Count;
            try{await ClaudeRemoteControl.Enable(native,binding,ledger,CancellationToken.None);throw new Exception("Uncertain remote enrollment repeated");}
            catch(InvalidOperationException){Check(native.Controls.Count==count,"Interrupted Remote Control enrollment is not automatically replayed");}
            try{await ClaudeRemoteControl.Enable(native,bindings[3],ledger,CancellationToken.None);throw new Exception("Foreign native session enrolled");}
            catch(InvalidDataException){Check(native.Controls.Count==count,"Foreign conversation rejected before native enrollment");}
        }
        return checks;
    }
    private static string Tail(Ledger ledger) => ledger.Get("bubble/" + Pin)!.Value.GetProperty("tail").GetString()!;
    private static bool Done(Ledger ledger, params int[] ids) => ids.All(id => ledger.Query("SELECT status FROM updates WHERE id=?", id) is { Count: 1 } rows && rows[0][0] is not ("received" or "dispatching"));
    private static async Task Wait(Func<bool> done, CancellationToken stop) { while (!done()) await Task.Delay(10, stop); }
    private static object Ask() => new { subtype = "can_use_tool", tool_name = "AskUserQuestion", input = new { preserve = "original", questions = new[] {
        new { question = "First full question?", header = "First", multiSelect = false, options = new[] { new { label = "A", description = "first" }, new { label = "B", description = "second" } } },
        new { question = "Second full question?", header = "Second", multiSelect = true, options = new[] { new { label = "A", description = "first" }, new { label = "B", description = "second" } } } } } };
    private sealed class Topics(string? failure = null, Ledger? ledger = null) : IClaudeTopics
    {
        public List<Claude> Opened = [];
        public Task<IClaudeNative> Open(Binding binding, CancellationToken stop)
        {
            var claude = new Claude(failure == "foreign-pin" && Opened.Count == 1 ? Guid.NewGuid().ToString("D") : binding.ThreadId,
                failInitialize: failure == "initialization-failure" && Opened.Count == 1, scenario: failure, ledger: ledger);
            Opened.Add(claude); return Task.FromResult<IClaudeNative>(claude);
        }
    }
    private sealed class MediaRace(Topics topics) : IAttachments
    {
        public Task<IReadOnlyList<StagedAttachment>> Stage(JsonElement message, Binding binding, long updateId, CancellationToken stop)
        {
            var claude = topics.Opened.Single();
            claude.Emit(new { type = "system", session_id = binding.ThreadId, subtype = "session_state_changed", state = "running" });
            claude.Emit(new { type = "system", session_id = binding.ThreadId, subtype = "session_state_changed", state = "idle" });
            return Task.FromResult<IReadOnlyList<StagedAttachment>>([new("document", "C:\\Protected\\asset.bin", 3, new string('a', 64), "fixture", null, false)]);
        }
    }
    private sealed class Claude(string pin, bool failInitialize = false, string? scenario = null, Ledger? ledger = null) : IClaudeNative
    {
        public uint Pid => 123; public string SessionId => pin; public bool Connected => !Disposed; public bool Disposed;
        public event Action<JsonElement>? Notification;
        public ConcurrentBag<(string Pin, JsonElement Content)> Inputs = new();
        public ConcurrentBag<(string Id, JsonElement Answer)> Answers = new();
        public ConcurrentBag<(string Kind, JsonElement Args)> Controls = new();
        public TaskCompletionSource<JsonElement> UsageReply = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private JsonElement? late;
        public void ConfirmLate()
        {
            var frame = late!.Value; var operation = ClaudeDelivery.ConfirmReplay(ledger!, pin, frame)!;
            Emit(new { type = "ccrelay_delivery_confirmed", session_id = pin, operation, uuid = frame.GetProperty("uuid").GetString() });
        }
        public void Emit(object value) => Notification?.Invoke(Json(value));
        public void Question(string id, object request) => Emit(new { type = "control_request", request_id = id, request });
        public Task<JsonElement> Initialize(CancellationToken stop)
        {
            if (failInitialize) throw new IOException("Fixture native initialization failure");
            if (scenario == "initialize-race") Emit(new { type = "system", session_id = pin, subtype = "session_state_changed", state = "idle" });
            if (scenario == "initialize-question") Question("restored", Ask());
            return Task.FromResult(Json(new { session_state = scenario == "initialize-race" ? "running" : "idle", models = new[] { new { value = "opus[1m]" } } }));
        }
        public Task<JsonElement> SendNow(string expectedSessionId, JsonElement content, CancellationToken stop)
        {
            Inputs.Add((expectedSessionId, content)); Emit(new { type = "system", session_id = pin, subtype = "session_state_changed", state = "running" });
            if (Inputs.Count == 1 && scenario is "late-delivery" or "ack-timeout-race" or "late-unrelated-hold")
            {
                var uuid = Guid.NewGuid().ToString("D"); var operation = ledger!.Attempt("claude/user/send-now", new { SessionId = pin, uuid, content });
                ledger.Outcome(operation, "unknown"); late = Json(new { type = "user", session_id = pin, uuid, parent_tool_use_id = (string?)null, message = new { role = "user", content } });
                if (scenario == "ack-timeout-race") ConfirmLate();
                throw new ClaudeDeliveryTimeout(operation, pin, uuid);
            }
            Emit(new { type = "stream_event", session_id = pin, @event = new { type = "content_block_delta", delta = new { type = "text_delta", text = "CLAUDE-TEXT" } } });
            return Task.FromResult(Json(new { type = "user", session_id = pin, uuid = Guid.NewGuid().ToString("D") }));
        }
        public Task<JsonElement> Control(string subtype, object parameters, CancellationToken stop, bool effect = true)
        {
            Controls.Add((subtype, Json(parameters)));
            if (subtype == "remote_control") return Task.FromResult(Json(new { bridge_session_id = "session_fixture", session_url = "https://claude.ai/code/session_fixture" }));
            if (subtype == "get_usage" && scenario == "slow-usage") return UsageReply.Task.WaitAsync(stop);
            if (subtype == "get_usage" && scenario == "failed-usage") throw new IOException("Fixture usage read failure");
            return Task.FromResult(subtype == "get_usage" ?
                Json(new { rate_limits_available = true, rate_limits = new { five_hour = new { utilization = 20 } } }) : Json(new { }));
        }
        public Task Answer(string id, object answer, CancellationToken stop) { Answers.Add((id, Json(answer))); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { Disposed = true; return ValueTask.CompletedTask; }
    }
    private sealed class Codex(RouterPolicy policy) : INative
    {
        public uint Pid => 7; public event Action<JsonElement>? Notification; public int Replies;
        public ConcurrentBag<(string Kind, JsonElement Args)> Calls = new(); public ConcurrentBag<JsonElement> Starts = new(), Steers = new();
        public void Event(string method, object parameters) => Notification?.Invoke(Json(new { method, @params = parameters }));
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            var args = Json(parameters); Calls.Add((method, args)); var id = args.GetProperty("threadId").GetString();
            if (method == "thread/resume") return Task.FromResult(Json(new { cwd = args.GetProperty("cwd").GetString(), thread = new { id },
                approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", sandbox = new { type = policy.NativeSandboxType } }));
            if (method == "thread/goal/get") return Task.FromResult(Json(new { goal = (object?)null }));
            if (method == "turn/start") { Starts.Add(args); Event("turn/started", new { threadId = id, turn = new { id = "native-turn" } }); return Task.FromResult(Json(new { turn = new { id = "native-turn" } })); }
            if (method == "turn/steer") { Steers.Add(args); return Task.FromResult(Json(new { turnId = "native-turn" })); }
            throw new Exception("Unexpected mixed fixture Codex RPC: " + method);
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) { Replies++; return Task.CompletedTask; }
    }
    private sealed class Bot(RouterPolicy policy, Binding[] bindings) : IBot
    {
        private readonly Channel<JsonElement> updates = Channel.CreateUnbounded<JsonElement>();
        public ConcurrentDictionary<long, JsonElement> Menus = new(); public ConcurrentDictionary<TopicAddress, string> Edits = new();
        public TaskCompletionSource Ready = new(TaskCreationOptions.RunContinuationsAsynchronously); public int Sends, MaxPolls; private int polling;
        public object Update(int id, Binding binding, string text) => new { update_id = id, message = new { from = new { id = policy.OwnerId, is_bot = false },
            chat = new { id = binding.Chat, is_forum = true }, message_thread_id = binding.Topic, message_id = id, text } };
        public void Post(params object[] batch) => updates.Writer.TryWrite(Json(batch));
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            var args = Json(parameters);
            if (method == "setMyCommands") { Menus[args.GetProperty("scope").GetProperty("chat_id").GetInt64()] = args.GetProperty("commands").Clone(); return Json(true); }
            if (method == "getMyCommands") return Menus[args.GetProperty("scope").GetProperty("chat_id").GetInt64()];
            if (method != "getUpdates") throw new Exception("Unexpected mixed fixture bot call: " + method);
            MaxPolls = Math.Max(MaxPolls, Interlocked.Increment(ref polling)); Ready.TrySetResult();
            try { return await updates.Reader.ReadAsync(stop); } finally { Interlocked.Decrement(ref polling); }
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        {
            Interlocked.Increment(ref Sends); var index = Array.FindIndex(bindings, b => b.Chat == chat && b.Topic == topic);
            if (index < 0) throw new Exception("Wrong mixed-topic send destination");
            Edits[bindings[index].Address] = text; return Task.FromResult(Json(new { message_id = 9000 + index }));
        }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        { var index = message >= 9000 ? message - 9000 : message - 900; if (bindings[index].Chat != chat) throw new Exception("Wrong mixed-topic chat"); Edits[bindings[index].Address] = text; return Task.CompletedTask; }
        public Task<JsonElement> SendAnswer(long chat, int topic, AnswerPart part, CancellationToken stop)
        {
            if (!bindings.Any(b => b.Chat == chat && b.Topic == topic)) throw new Exception("Wrong mixed final destination");
            return Task.FromResult(Json(new { message_id = 10000 + topic }));
        }
    }
}
