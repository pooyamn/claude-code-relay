using System.Text.Json;

namespace KhadangRouter;

public static class SelfTests
{
    public static void Run()
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        var policy = new RouterPolicy("TheKhadangBot", 123, 456, -100123, "S-1-5-21-1-2-3-1001",
            "C:\\Native\\codex.exe", new string('a', 64), "C:\\Protected\\token.dpapi", "C:\\Protected\\state", "C:\\Workspaces");
        policy.Validate(); Check(true, "Valid PC policy"); policy.Workspace("C:\\Workspaces\\lg-magic", verifyFilesystem: false);
        foreach (var bad in new[] { "/Users/pouya/lg", "C:\\Workspaces\\..\\Secret", "\\\\host\\share", "C:\\Workspaces\\x:ads", "C:/Workspaces/lg", "C:\\Other\\lg" })
        {
            try { policy.Workspace(bad, verifyFilesystem: false); throw new Exception("Unsafe path accepted"); }
            catch (InvalidDataException) { checks++; }
        }
        JsonElement Message(long id = 456, bool forwarded = false) => JsonSerializer.SerializeToElement(new Dictionary<string, object> {
            ["from"] = new { id, is_bot = false }, ["chat"] = new { id = -100123, is_forum = true },
            [forwarded ? "forward_origin" : "text"] = "test" });
        Check(policy.OwnerMessage(Message()), "Owner accepted"); Check(!policy.OwnerMessage(Message(457)), "Foreign sender denied");
        Check(!policy.OwnerMessage(Message(forwarded: true)), "Forwarded owner text denied");
        foreach (var malformed in new[] { "null", "{}", "{\"from\":{\"id\":\"456\"}}", "{\"from\":{\"id\":456}}" })
            Check(!policy.OwnerMessage(JsonDocument.Parse(malformed).RootElement), "Malformed message fails closed");
        var bubble = new RollingBubble(); bubble.Append(new string('x', 9000) + "🙂 end");
        var rendered = bubble.Render(TimeSpan.FromSeconds(63), new string('g', 400));
        Check(rendered.Length <= 3900 && rendered.Contains("Working (1m 3s)"), "Bubble bounded with footer");
        Check(!char.IsLowSurrogate(rendered[0]), "Rolling tail does not split an emoji");
        var root = Path.Combine(Path.GetTempPath(), "khadang-router-tests-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        var dbPath = Path.Combine(root, "router.db"); string attempt;
        using (var ledger = new Ledger(dbPath))
        {
            Check(ledger.Receive(100, "{\"message\":\"one\"}") && !ledger.Receive(100, "{\"message\":\"one\"}"), "Durable deduplication");
            Check(ledger.Offset == 101 && ledger.Pending().Count == 1, "Committed offset and pending update");
            Check(ledger.Claim(100) && !ledger.Claim(100), "Single dispatch claim");
            try { ledger.Receive(100, "changed"); throw new Exception("Changed payload accepted"); } catch (InvalidDataException) { checks++; }
            attempt = ledger.Attempt("native/turn/start", new { input = "test" });
            var binding = new Binding(-100123, 42, "LG", "C:\\Workspaces\\lg-magic", "native-id");
            ledger.Bind(binding); ledger.Bind(binding);
            try { ledger.Bind(binding with { ThreadId = "wrong" }); throw new Exception("Binding replaced"); } catch (InvalidDataException) { checks++; }
        }
        using (var ledger = new Ledger(dbPath))
        {
            Check(ledger.Unknown == 2 && ledger.Pending().Count == 0 && !ledger.Claim(100), "Restart holds uncertain input and external effect");
            Check(ledger.Bindings().Single().ThreadId == "native-id", "Exact native ID survives restart");
            ledger.Confirm(attempt, JsonSerializer.SerializeToElement(new { ok = true }));
            Check(ledger.Unknown == 2, "Unknown attempt cannot be blindly confirmed/replayed");
        }
        using (var ledger = new Ledger(Path.Combine(root, "display-timeouts.db")))
        {
            var edit = ledger.Attempt("telegram/editMessageText", new { chat_id = -100123, message_id = 7, text = "Working" });
            ledger.Outcome(edit, "unknown");
            Check(ledger.Unknown == 0 && ledger.PresentationUnknown == 1, "Unknown display edit does not globally stop native input");
            ledger.Exec("UPDATE operations SET status='unknown-presentation' WHERE id=?", edit);
            Check(ledger.Unknown == 0 && ledger.PresentationUnknown == 1, "Live display classification preserves visible uncertainty");
            var send = ledger.Attempt("telegram/sendMessage", new { chat_id = -100123, text = "Final" });
            ledger.Outcome(send, "unknown");
            Check(ledger.Unknown == 1, "Unknown initial message send still holds native admission");
            var native = ledger.Attempt("claude/user/send-now", new { SessionId = "native-session" });
            ledger.Outcome(native, "unknown");
            Check(ledger.Unknown == 2, "Unknown native input still holds admission");
            ledger.Receive(101, "{}"); ledger.Claim(101);
        }
        using (var ledger = new Ledger(Path.Combine(root, "display-timeouts.db")))
            Check(ledger.Unknown == 3 && ledger.PresentationUnknown == 1, "Restart keeps uncertain native/send/dispatch holds and separate display audit");
        checks += NativeViewTests.Run();
        checks += NativeChannelTests.Run(root).GetAwaiter().GetResult();
        checks += LinuxCodexRuntimeTests.Run(policy).GetAwaiter().GetResult();
        checks += LinuxClaudeRuntimeTests.Run(policy, root).GetAwaiter().GetResult();
        checks += ClaudeNativeStreamTests.Run(root).GetAwaiter().GetResult();
        checks += NativeBrokerTests.Run(root).GetAwaiter().GetResult();
        checks += NativeBrokerWireTests.Run(root).GetAwaiter().GetResult();
        checks += RemoteTests.Run().GetAwaiter().GetResult();
        checks += JoinedTests.Run(root, policy).GetAwaiter().GetResult();
        checks += BubbleBoundaryTests.Run(root, policy).GetAwaiter().GetResult();
        checks += BubbleFormatTests.Run();
        checks += FinalAnswerTests.Run(root, policy).GetAwaiter().GetResult();
        checks += GoalAnswerTests.Run(root, policy).GetAwaiter().GetResult();
        checks += ModelSwitchTests.Run(root, policy).GetAwaiter().GetResult();
        checks += ActiveAttachmentTests.Run(root, policy).GetAwaiter().GetResult();
        checks += GoalTests.Run(root, policy).GetAwaiter().GetResult();
        checks += QuotaTests.Run(root, policy).GetAwaiter().GetResult();
        checks += AttachmentTests.Run(root, policy).GetAwaiter().GetResult();
        checks += RoutingTests.Run(root, policy).GetAwaiter().GetResult();
        checks += ParticipantTests.Run(root, policy).GetAwaiter().GetResult();
        checks += MixedRoutingTests.Run(root, policy).GetAwaiter().GetResult();
        // A unique test-owned directory, never a workspace/service path.
        Directory.Delete(root, recursive: true);
        Console.WriteLine("All " + checks + " PC-router checks passed (no credentials/network/models).");
    }
}
