using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

// Deterministic display labels, not another model call or command interpreter.
// Never evaluate scripts or expose arbitrary arguments to explain a tool call.
internal static class ToolSummary
{
    public static string Compact(string text, int bound = 64)
    {
        var clean = NativeGoal.Literal(text);
        if (clean.Length <= bound) return clean;
        var end = bound - 1;
        if (char.IsHighSurrogate(clean[end - 1])) end--;
        var space = clean.LastIndexOf(' ', end - 1, end);
        if (space >= end / 2) end = space;
        return clean[..end].TrimEnd() + "…";
    }

    public static string Field(JsonElement item, string name) => item.ValueKind == JsonValueKind.Object &&
        item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()! : "";

    public static string File(string path) => Compact(path.Replace('\\', '/').TrimEnd('/').Split('/').Last(), 40);

    public static string Shell(string command, string description = "")
    {
        // Native Claude descriptions are purpose-written summaries. Prefer them
        // when they are short prose, not an embedded command/source dump.
        if (!string.IsNullOrWhiteSpace(description) && description.Length <= 160 &&
            !description.Contains('\n') && !Regex.IsMatch(description, @"[{};]|\$\(|(?i)-encodedcommand|<<|https?://"))
            return Compact(description);
        var first = command.TrimStart().Split('\n')[0].TrimEnd('\r');
        var executable = Regex.Match(first, "^(?:\"([^\"]+)\"|'([^']+)'|([^\\s;|&]+))");
        var token = executable.Success ? executable.Groups.Cast<Group>().Skip(1).First(g => g.Success).Value : "";
        var name = token.Replace('\\', '/').Split('/').Last();
        if (Regex.IsMatch(name, @"^(?i)python(?:[0-9.]+)?(?:\.exe)?$")) return "Run Python script";
        if (Regex.IsMatch(name, @"^(?i)(?:pwsh|powershell)(?:\.exe)?$") || first.StartsWith('$')) return "Run PowerShell script";
        if (Regex.IsMatch(name, @"^(?i)(?:ssh|scp)(?:\.exe)?$")) return name.StartsWith("scp", StringComparison.OrdinalIgnoreCase) ? "Copy remote files" : "Run remote command";
        if (Regex.IsMatch(name, @"^(?i)(?:bash|sh|zsh)(?:\.exe)?$") || command.Contains("<<")) return "Run shell script";
        if (Regex.IsMatch(name, @"^(?i)(?:node|ruby|perl)(?:\.exe)?$")) return "Run " + name.Replace(".exe", "", StringComparison.OrdinalIgnoreCase) + " script";
        if (Regex.IsMatch(first, @"^(?i)Get-(?:ScheduledTask|Service|CimInstance|ItemProperty)\b")) return "Inspect Windows settings";
        var operation = Regex.Match(first, @"(?:^|[/\\])(?i)(dotnet|npm|pnpm|yarn|cargo|git)(?:\.exe)?[""']?\s+(?:run\s+)?([a-z-]+)");
        if (operation.Success)
        {
            var op = operation.Groups[2].Value.ToLowerInvariant();
            var label = op switch {
                "test" or "check" or "lint" => "Run checks", "build" => "Build project", "publish" => "Publish build",
                "status" => "Check repository status", "diff" => "Inspect changes", "log" or "show" => "Inspect commit history",
                "commit" => "Commit changes", "push" => "Push commits", "fetch" or "pull" => "Fetch repository updates",
                "install" or "restore" or "ci" => "Install dependencies", _ => "Run " + operation.Groups[1].Value.ToLowerInvariant() + " " + op
            };
            if (op == "build" && Regex.IsMatch(first, @"(?i)\b(?:test|--self-test)\b")) label = "Build and run checks";
            return Compact(label);
        }
        if (Regex.IsMatch(name, @"^(?i)(rg|grep|find)(?:\.exe)?$")) return "Search files";
        if (Regex.IsMatch(name, @"^(?i)(sed|head|tail|cat|less)(?:\.exe)?$")) return "Read files";
        if (Regex.IsMatch(name, @"^(?i)(ls|dir)(?:\.exe)?$")) return "List files";
        // Unknown commands show only a simple executable name, never its flags,
        // source, credentials, URLs or an arbitrary first 300 characters.
        return Regex.IsMatch(name, @"\A[A-Za-z][A-Za-z0-9._-]{0,31}\z") ? "Run " + name : "Run command";
    }

    public static string Command(JsonElement item)
    {
        if (item.TryGetProperty("commandActions", out var actions) && actions.ValueKind == JsonValueKind.Array)
        {
            var reads = 0; var searches = 0; var lists = 0; string file = "";
            foreach (var action in actions.EnumerateArray().Take(128))
                switch (Field(action, "type"))
                {
                    case "read": reads++; if (file.Length == 0) file = File(Field(action, "name")); break;
                    case "search": searches++; break;
                    case "listFiles": lists++; break;
                }
            var labels = new List<string>();
            if (reads != 0) labels.Add(reads == 1 && file.Length > 0 ? "Read " + file : "Read " + reads + " files");
            if (searches != 0) labels.Add(searches == 1 ? "Search files" : searches + " searches");
            if (lists != 0) labels.Add("List files");
            if (labels.Count != 0) return Compact(string.Join(" · ", labels));
        }
        return Shell(Field(item, "command"));
    }

    public static string Changes(JsonElement item)
    {
        if (!item.TryGetProperty("changes", out var changes) || changes.ValueKind != JsonValueKind.Array) return "file";
        var count = changes.GetArrayLength();
        return count == 1 ? File(Field(changes[0], "path")) : count + " files";
    }

    public static string Dynamic(JsonElement item)
    {
        var tool = Field(item, "tool");
        if (tool is not ("exec" or "functions.exec")) return Compact("Tool " + tool);
        var source = item.TryGetProperty("arguments", out var arguments) && arguments.ValueKind == JsonValueKind.Object
            ? Field(arguments, "code") : "";
        if (source.Length == 0 || source.Length > 65536) return "Run tools";
        var labels = new List<string>();
        foreach (Match call in Regex.Matches(source, @"\btools\.(exec_command|write_stdin|apply_patch|view_image|web__run|clock__curr_time)\s*\(").Take(16))
        {
            var name = call.Groups[1].Value;
            var label = name switch {
                "apply_patch" => "Edit files", "write_stdin" => "Continue command", "view_image" => "Inspect image",
                "web__run" => "Look up sources", "clock__curr_time" => "Check time", _ => "Run command"
            };
            if (name == "exec_command")
            {
                // Decode only a literal JSON string in the known cmd field.
                // Expressions, templates and single-quoted source are not evaluated.
                var literal = Regex.Match(source[(call.Index + call.Length)..], "^\\s*\\{\\s*cmd\\s*:\\s*(\"(?:[^\"\\\\]|\\\\.)*\")");
                if (literal.Success)
                    try { label = Shell(JsonSerializer.Deserialize<string>(literal.Groups[1].Value) ?? ""); }
                    catch (JsonException) { /* Display fallback; native input is unchanged. */ }
            }
            labels.Add(label);
        }
        var distinct = labels.Distinct().ToArray();
        return distinct.Length == 0 ? "Run tools" : Compact(string.Join(" · ", distinct.Take(2)) + (distinct.Length > 2 ? " + " + (distinct.Length - 2) + " more" : ""));
    }
}
