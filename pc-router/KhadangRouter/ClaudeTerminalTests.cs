using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

public static class ClaudeTerminalTests
{
    public static int Run(string root, RouterPolicy policy)
    {
        int checks = 0;
        void Check(bool condition, string label) { if (!condition) throw new Exception(label); checks++; }
        JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
        var bash = Json(new { id = "bash", name = "Bash", input = new { command = "dotnet test " + new string('x', 8000), description = "Run project tests" } });
        var header = ClaudeTerminalView.Tool(bash);
        Check(header.StartsWith("⏺ Bash(Run project tests)") && header.Contains("⎿ Running") && header.Length < 100,
            "Claude Bash display prefers the real short description to a command dump");
        var script = Json(new { name = "Bash", input = new { command = "powershell.exe -EncodedCommand " + new string('x', 10000) } });
        Check(ClaudeTerminalView.Tool(script).StartsWith("⏺ Bash(Run PowerShell script)") && ClaudeTerminalView.Tool(script).Length < 100, "Long Claude commands get the same compact purpose label as Codex");
        var longDescription = Json(new { name = "Bash", input = new { command = "dotnet build", description = "Build the router and verify the changed presentation using deterministic fixture tests before publication" } });
        Check(ClaudeTerminalView.Tool(longDescription).Length < 100 && !ClaudeTerminalView.Tool(longDescription).Contains("publication"), "Long real descriptions fit one short tool header");
        Check(ToolSummary.Shell("git status", "token=PRIVATE-CANARY") == "token=[REDACTED]", "Purpose descriptions receive native credential redaction");
        var result = ClaudeTerminalView.Tool(bash, "completed", Json(new { content = "All tests passed\n17 checks verified\nextra output" }));
        Check(result.Contains("All tests passed") && result.Contains("17 checks verified") && !result.Contains("extra output"), "Bash result shows two short actual output lines");
        Check(!ClaudeTerminalView.Tool(bash, "completed", Json(new { content = "token=PRIVATE-CANARY" })).Contains("PRIVATE-CANARY"), "Credential-shaped output never becomes a terminal excerpt");
        Check(!ClaudeTerminalView.Tool(bash, "completed", Json(new { content = "{\"private_key\":\"PRIVATE-CANARY\"}" })).Contains("PRIVATE-CANARY"), "Structured output is not dumped into the bubble");
        var read = Json(new { id = "read", name = "Read", input = new { file_path = "/long/private/path/board.kicad_pcb" } });
        var readDisplay = ClaudeTerminalView.Tool(read, "completed", Json(new { content = "PRIVATE-FILE-CONTENTS" }));
        Check(readDisplay.Contains("Read(board.kicad_pcb)") && !readDisplay.Contains("/long") && !readDisplay.Contains("PRIVATE-FILE"), "File tools show the basename, not private file contents or path dumps");
        var partial = new ClaudeToolInput(Json(new { type = "tool_use", id = "partial", name = "Bash", input = new { } }));
        Check(partial.Append("{\"command\":\"dotnet test\",") == null, "Incomplete tool arguments do not hold native work");
        var complete = partial.Append("\"description\":\"Build and test\"}");
        Check(complete != null && ClaudeTerminalView.Tool(complete.Value).Contains("Build and test"), "Incremental arguments provide the missing real tool description");
        Check(new ClaudeToolInput(read).Append(new string('x', 17000)) == null, "Large display arguments are discarded without a native hold");
        var rolling = new RollingBubble(); rolling.Upsert("cagent:first", "Keep this explanation visible.");
        for (int i = 0; i < 20; i++) rolling.Upsert("ctool:" + i, ClaudeTerminalView.Tool(read, i == 0 ? "failed" : "completed"), important: i == 0);
        var rendered = rolling.Render(TimeSpan.FromSeconds(63));
        Check(rendered.Contains("⏺ Keep this explanation") && rendered.Contains("16 earlier tool calls"), "Consecutive tool spam compacts without erasing assistant text");
        Check(rendered.Contains("Error") && rendered.Split("Read(board.kicad_pcb)").Length == 5, "Failed tool plus last three calls remain visible");
        rolling.Upsert("question:one", "Please confirm the board pin.");
        Check(rolling.Render(TimeSpan.FromSeconds(63)).Contains("Please confirm") && rendered.EndsWith("Working (1m 3s)"), "Pending question and bottom working timer remain visible");
        var longText = new RollingBubble(); longText.Upsert("cagent:long", new string('x', 8500) + "\nLATEST-CLAUDE-TEXT");
        longText.Upsert("ctool:read", ClaudeTerminalView.Tool(read));
        Check(longText.Render(TimeSpan.Zero).Contains("LATEST-CLAUDE-TEXT"), "Oversized text is trimmed by lines, not discarded as an entire block when a tool arrives");
        Check(rolling.Tail.Length <= 7000 && rolling.Render(TimeSpan.Zero).Length <= 3900, "Persisted display and single Telegram message stay bounded");

        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        using var ledger = new Ledger(Path.Combine(root, "claude-terminal.db"));
        var native = new Native(); var router = new Router(policy, ledger, new Bot(), native);
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        var binding = new Binding(policy.ChatId, 53, "Claude view fixture", policy.WorkspaceRoot + "\\fixture", "5a5e6b71-a837-4a30-a021-929a32bff048", Backend: "claude");
        var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
        var onClaude = typeof(Router).GetMethod("OnClaude", flags)!;
        void Event(object value) => onClaude.Invoke(router, new[] { session, (object)Json(value) });
        string Text() => ((RollingBubble)type.GetField("Bubble")!.GetValue(session)!).Render(TimeSpan.Zero);
        Event(new { type = "system", session_id = binding.ThreadId, subtype = "session_state_changed", state = "running" });
        Event(new { type = "stream_event", session_id = binding.ThreadId, @event = new { type = "message_start", message = new { id = "message" } } });
        Event(new { type = "stream_event", session_id = binding.ThreadId, @event = new { type = "content_block_start", index = 0, content_block = new { type = "text", text = "Initial text " } } });
        Event(new { type = "stream_event", session_id = binding.ThreadId, @event = new { type = "content_block_delta", index = 0, delta = new { type = "text_delta", text = "and continuation." } } });
        Check(Text().Contains("⏺ Initial text and continuation."), "Router preserves both block-start text and subsequent stream deltas");
        Event(new { type = "stream_event", session_id = binding.ThreadId, @event = new { type = "content_block_start", index = 1, content_block = new { type = "tool_use", id = "partial", name = "Bash", input = new { } } } });
        Event(new { type = "stream_event", session_id = binding.ThreadId, @event = new { type = "content_block_delta", index = 1, delta = new { type = "input_json_delta", partial_json = "{\"command\":\"dotnet test\",\"description\":\"Test fixture\"}" } } });
        Check(Text().Contains("Bash(Test fixture)"), "Router updates an initially empty tool header from argument deltas");
        Event(new { type = "user", session_id = binding.ThreadId, uuid = "completed", message = new { content = new[] { new { type = "tool_result", tool_use_id = "partial", content = "Tests passed" } } } });
        Check(Text().Contains("Tests passed"), "Real tool completion updates its existing row, not another call row");
        Event(new { type = "assistant", session_id = binding.ThreadId, uuid = "late", message = new { id = "tool", content = new[] { new { type = "tool_use", id = "partial", name = "Bash", input = new { command = "dotnet test", description = "Test fixture" } } } } });
        Check(!Text().Contains("⎿ Running") && Text().Contains("Tests passed"), "Late authoritative tool metadata preserves the completed call and its output");
        Check(!((bool)type.GetField("Held")!.GetValue(session)!), "Display-only stream updates do not hold native work or invoke controls");
        return checks;
    }
    private sealed class Native : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true) => throw new Exception("No native action");
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No native reply");
    }
    private sealed class Bot : IBot
    {
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new Exception("No Telegram action");
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => throw new Exception("No Telegram send");
        public Task Edit(long chat, int message, string text, CancellationToken stop) => throw new Exception("No Telegram edit");
    }
}
