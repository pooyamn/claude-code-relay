using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

// Display only. Native content is never interpreted as a Telegram command,
// authenticated human identity, approval or new router input. Do not mirror
// private attachment URLs/paths, MCP arguments or arbitrary tool result JSON.
public static class NativeEventView
{
    private static string Field(JsonElement item, string name, int bound = 160) =>
        item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? RollingBubble.SafeTail(NativeGoal.Literal(value.GetString()!), bound) : "";

    public static void VerifySteer(JsonElement reply, string expected)
    {
        if (reply.ValueKind != JsonValueKind.Object || !reply.TryGetProperty("turnId", out var id) ||
            id.ValueKind != JsonValueKind.String || id.GetString() != expected)
            throw new InvalidDataException("Native steering acknowledgment does not confirm the exact active turn; no replay");
    }

    public static string User(JsonElement item)
    {
        if (Field(item, "type") != "userMessage" || !item.TryGetProperty("content", out var content) || content.ValueKind != JsonValueKind.Array) return "";
        var parts = new List<string>(); int inspected = 0, attachments = 0;
        foreach (var part in content.EnumerateArray())
        {
            if (++inspected > 32) { parts.Add("[additional input retained in native history]"); break; }
            var type = Field(part, "type");
            if (type == "text") parts.Add(CompactLegacyInput(Field(part, "text", 800)));
            else if (type is "image" or "localImage" or "file") attachments++;
        }
        if (attachments != 0) parts.Add("[" + attachments + " attachment(s); inspect in native client]");
        var text = RollingBubble.SafeTail(string.Join(" ", parts.Where(p => p.Length > 0)), 1200);
        return text.Length == 0 ? "" : "\n↪ " + text + "\n";
    }

    // A native userMessage is an observed conversational boundary, not proof
    // of human identity/approval. Exclude provider-internal goal continuations;
    // no heuristics about whether assistant prose "sounds like" an answer.
    internal static bool DirectInput(JsonElement item) =>
        item.TryGetProperty("content", out var content) && content.ValueKind == JsonValueKind.Array &&
        content.EnumerateArray().Any(part => part.TryGetProperty("type", out var type) &&
            (type.GetString() is "image" or "localImage" or "file" || type.GetString() == "text" &&
             part.TryGetProperty("text", out var text) && text.ValueKind == JsonValueKind.String &&
             !string.IsNullOrWhiteSpace(text.GetString()) && !text.GetString()!.TrimStart().StartsWith("<codex_internal_context", StringComparison.Ordinal)));

    // Display compatibility only: leave native history and durable provenance
    // intact. Previously formatted inputs and restored bubbles need not keep
    // showing the retired verbose header after the new formatter is deployed.
    internal static string CompactLegacyInput(string text) => Regex.Replace(text,
        @"\A\[Telegram owner [0-9]{1,20}; message [0-9]{1,20}\] ", "");
    internal static string CompactLegacyBubble(string text) => Regex.Replace(text,
        @"(?m)^↪ Native input: (?:\[Telegram owner [0-9]{1,20}; message [0-9]{1,20}\] )?", "↪ ");

    public static string Tool(JsonElement item, bool completed)
    {
        var type = Field(item, "type");
        if (type is "" or "agentMessage" or "userMessage" or "reasoning" or "functionCallOutput") return "";
        var name = type switch {
            "mcpToolCall" => ToolSummary.Compact("MCP " + Field(item, "server") + "/" + Field(item, "tool")),
            "dynamicToolCall" => ToolSummary.Dynamic(item),
            "commandExecution" => ToolSummary.Command(item),
            "fileChange" => "Edit " + ToolSummary.Changes(item),
            "webSearch" => "Search web",
            "imageView" => "View image " + ToolSummary.File(Field(item, "path")),
            "contextCompaction" => "Compact context",
            "plan" or "todoList" => "Update plan",
            _ => type
        };
        var status = Field(item, "status", 80);
        var suffix = status.Length == 0 ? completed ? "completed" : "started" : status;
        if (type == "commandExecution" && completed && item.TryGetProperty("exitCode", out var code) && code.ValueKind == JsonValueKind.Number && code.TryGetInt32(out var exit))
            suffix += "; exit " + exit;
        var mark = Failed(item) ? "✗" : completed ? "✓" : "⏳";
        return "\n" + mark + " " + name + " (" + suffix + ")\n";
    }
    public static bool Failed(JsonElement item) => Field(item, "status") is "failed" or "declined" ||
        item.TryGetProperty("exitCode", out var code) && code.ValueKind == JsonValueKind.Number && code.TryGetInt32(out var exit) && exit != 0;
    public static string ClaudeTool(JsonElement block, string status = "started")
    {
        var name = Field(block, "name");
        var label = name;
        if (block.TryGetProperty("input", out var input) && input.ValueKind == JsonValueKind.Object)
        {
            var file = Field(input, "file_path");
            if (name is "Read" or "Write" or "Edit" && file.Length > 0) label += " " + ToolSummary.File(file);
            else if (name == "Bash") label = ToolSummary.Shell(ToolSummary.Field(input, "command"), ToolSummary.Field(input, "description"));
            else if (name == "Grep") label = "Search files";
            else if (name == "Glob") label = "List files";
        }
        return (status == "failed" ? "✗ " : status == "completed" ? "✓ " : "⏳ ") + label;
    }
}
