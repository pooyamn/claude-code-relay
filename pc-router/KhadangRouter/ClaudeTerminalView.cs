using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

// A terminal-like display of native stream evidence, never a second TUI/writer.
internal static class ClaudeTerminalView
{
    private static string Short(string value, int bound = 100)
    {
        var clean = NativeGoal.Literal(value);
        if (clean.Length <= bound) return clean;
        var end = bound - 1;
        if (char.IsHighSurrogate(clean[end - 1])) end--;
        return clean[..end] + "…";
    }
    private static string Field(JsonElement item, string name) => item.ValueKind == JsonValueKind.Object &&
        item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()! : "";
    public static string Tool(JsonElement block, string status = "started", JsonElement? result = null)
    {
        var name = Short(Field(block, "name"), 60);
        var label = name;
        var input = block.TryGetProperty("input", out var rawInput) && rawInput.ValueKind == JsonValueKind.Object ? rawInput : default;
        var file = Field(input, "file_path");
        if (name is "Read" or "Write" or "Edit" && file.Length > 0)
            label += "(" + Short(file.Split('/', '\\').Last(), 80) + ")";
        else if (name == "Bash")
        {
            var description = Field(input, "description");
            var command = Field(input, "command").Split('\n')[0];
            var detail = Short(description.Length > 0 ? description : command);
            if (detail.Length > 0) label += "(" + detail + ")";
        }
        else if (name is "Grep" or "Glob")
        {
            var pattern = Short(Field(input, "pattern"), 70);
            if (pattern.Length > 0) label += "(" + pattern + ")";
        }
        var summary = status == "failed" ? "Error — inspect native session" : status == "completed" ? "Done" : "Running…";
        // File/MCP results may contain entire private files, images or credential
        // JSON. Never dump them. Plain Bash output has at most two short lines;
        // credential-oriented commands and structured/secret output stay private.
        if (result is { } output && name == "Bash" && input.ValueKind == JsonValueKind.Object &&
            ClaudeInput.Reviewable(input) && !Regex.IsMatch(Field(input, "command"), @"(?i)token|password|secret|credential|authorization|\.ssh|\.env|printenv|\benv\b"))
        {
            var text = output.TryGetProperty("content", out var content) && content.ValueKind == JsonValueKind.String ? content.GetString()! : "";
            if (text.Length > 0 && !text.TrimStart().StartsWith('{') && !text.TrimStart().StartsWith('[') &&
                !text.Contains("PRIVATE KEY", StringComparison.Ordinal) && !NativeGoal.Redact(text).Contains("[REDACTED]", StringComparison.Ordinal))
            {
                using var lines = new StringReader(text);
                var excerpt = new List<string>(); string? line; int inspected = 0;
                while (excerpt.Count < 2 && inspected++ < 12 && (line = lines.ReadLine()) != null)
                    if (!string.IsNullOrWhiteSpace(line)) excerpt.Add(Short(line, 110));
                if (excerpt.Count != 0) summary = (status == "failed" ? "Error: " : "") + string.Join("\n  ⎿ ", excerpt);
            }
        }
        return "⏺ " + label + "\n  ⎿ " + summary;
    }
}

// Partial arguments are display-only. A malformed/large fragment never holds
// native work, becomes authorization, or replaces an authoritative tool block.
internal sealed class ClaudeToolInput(JsonElement block)
{
    private readonly JsonElement initial = block.Clone();
    private readonly StringBuilder json = new();
    private bool oversized;
    public JsonElement? Append(string fragment)
    {
        if (oversized || fragment.Length > 16384 - json.Length) { oversized = true; json.Clear(); return null; }
        json.Append(fragment);
        if (!json.ToString().TrimEnd().EndsWith('}')) return null;
        try
        {
            using var parsed = JsonDocument.Parse(json.ToString());
            if (parsed.RootElement.ValueKind != JsonValueKind.Object) return null;
            var fields = initial.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone());
            fields["input"] = parsed.RootElement.Clone();
            return JsonSerializer.SerializeToElement(fields);
        }
        catch (JsonException) { return null; }
    }
}
