using System.Text.Json;

namespace KhadangRouter;

public static class NativeViewTests
{
    public static int Run()
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
        NativeEventView.VerifySteer(Json(new { turnId = "active" }), "active"); checks++;
        foreach (var reply in new[] { Json(new { }), Json(new { turnId = "foreign" }), Json(new { turnId = 1 }), Json((object?)null!) })
        {
            try { NativeEventView.VerifySteer(reply, "active"); throw new Exception("Unverified native steering accepted"); }
            catch (InvalidDataException) { checks++; }
        }
        var user = Json(new { type = "userMessage", content = new object[] {
            new { type = "text", text = "/goal clear; Have you updated the source? Pushed? token=PRIVATE-CANARY" },
            new { type = "localImage", path = "C:\\PRIVATE-PATH\\secret.png" },
            new { type = "image", url = "https://PRIVATE-URL.invalid/?secret=private" } } });
        var display = NativeEventView.User(user);
        Check(display.StartsWith("\n↪ ") && !display.Contains("Native input:") && display.Contains("/goal clear") && display.Contains("Pushed?"), "Compact input is visible literal display, not a routed control");
        Check(NativeEventView.User(Json(new { type = "userMessage", content = new[] { new { type = "text", text = "Test" } } })) == "\n↪ Test\n",
            "Short input has exactly the compact arrow prefix");
        Check(NativeEventView.User(Json(new { type = "userMessage", content = new[] { new { type = "text", text = "[Telegram owner 110123423; message 13604]\nTest" } } })) == "\n↪ Test\n",
            "Legacy native input header is compacted in display, not replayed");
        var legacyBubble = new RollingBubble(); legacyBubble.Append("\n↪ Native input: [Telegram owner 110123423; message 13604] Test\nReceived—I'm here.");
        var legacyRendered = legacyBubble.Render(TimeSpan.FromSeconds(1), state: "Done");
        Check(legacyRendered.StartsWith("↪ Test\nReceived—I'm here.") && !legacyRendered.Contains("110123423") && legacyRendered.Contains("Done ("),
            "Restored existing bubble compacts without rewriting native history or hiding its footer");
        Check(NativeEventView.CompactLegacyBubble("Assistant quoted Native input: keep this text") == "Assistant quoted Native input: keep this text",
            "Non-prefix text is not rewritten by display compatibility");
        Check(display.Contains("2 attachment(s)") && !display.Contains("PRIVATE-PATH") && !display.Contains("PRIVATE-URL"), "Attachment count does not expose private paths or URLs");
        Check(!display.Contains("PRIVATE-CANARY") && display.Contains("REDACTED"), "Known credential-shaped input is redacted");
        var longInput = NativeEventView.User(Json(new { type = "userMessage", content = new[] { new { type = "text", text = new string('x', 30000) + "🙂 LAST" } } }));
        Check(longInput.Length < 1250 && longInput.Contains("🙂 LAST"), "Input reflection is bounded and retains latest text");
        Check(NativeEventView.User(Json(new { type = "userMessage", content = 1 })) == "" && NativeEventView.User(Json(new { type = "userMessage", content = new object[] { 1, new { type = "text", text = 2 } } })) == "", "Malformed optional display data is ignored safely");
        var many = NativeEventView.User(Json(new { type = "userMessage", content = Enumerable.Range(0, 100).Select(i => new { type = "text", text = "part" + i }).ToArray() }));
        Check(many.Contains("additional input retained") && !many.Contains("part99"), "Display-part bound does not pretend to show full input");
        var mcp = Json(new { type = "mcpToolCall", server = "fixture", tool = "inspect", status = "inProgress", arguments = "PRIVATE-ARGS", result = "PRIVATE-RESULT" });
        var tool = NativeEventView.Tool(mcp, false);
        Check(tool.Contains("MCP fixture/inspect") && tool.Contains("inProgress"), "MCP tool name and lifecycle visible");
        Check(!tool.Contains("PRIVATE-ARGS") && !tool.Contains("PRIVATE-RESULT"), "No arbitrary MCP argument or result mirroring");
        Check(NativeEventView.Tool(Json(new { type = "dynamicToolCall", tool = "fixture", status = "failed" }), true).Contains("Tool fixture (failed)"), "Dynamic tool failure visible");
        Check(NativeEventView.Tool(Json(new { type = "commandExecution", command = "whoami /user", status = "completed", exitCode = 1 }), true).Contains("exit 1"), "Command completion exit code visible");
        Check(NativeEventView.Tool(Json(new { type = "commandExecution", exitCode = "bad" }), true).Contains("completed"), "Malformed optional exit code cannot break event transport");
        Check(NativeEventView.Tool(Json(new { type = "agentMessage" }), true) == "" && NativeEventView.Tool(Json(new { type = "userMessage" }), false) == "", "Message items do not become fake tool calls");
        return checks;
    }
}
