using System.Text.Json;
using System.Text.Json.Serialization;

namespace KhadangRouter;

public sealed record RouterPolicy(string BotUsername, long BotId, long OwnerId, long ChatId,
    string OwnerSid, string CodexExecutable, string CodexSha256, string CredentialFile,
    string StateDirectory, string WorkspaceRoot, int MaximumSessions = 3, int StartSpacingSeconds = 5,
    bool OwnerFullAccess = false, ChatRoute[]? AdditionalChats = null, string? LinuxWorkspaceRoot = null,
    LinuxCodexRuntime? LinuxCodex = null, LinuxClaudeRuntime? LinuxClaude = null, long[]? ParticipantIds = null,
    bool PersistentClaudeWorkers = false)
{
    [JsonIgnore] public string NativeApprovalPolicy => OwnerFullAccess ? "never" : "on-request";
    [JsonIgnore] public string NativePermissionProfile => OwnerFullAccess ? ":danger-full-access" : ":workspace";
    [JsonIgnore] public string NativeSandboxType => OwnerFullAccess ? "dangerFullAccess" : "workspaceWrite";
    public static RouterPolicy Load(string path)
    {
        var policy = JsonSerializer.Deserialize<RouterPolicy>(File.ReadAllText(path), new JsonSerializerOptions {
            PropertyNameCaseInsensitive = false, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
        }) ?? throw new InvalidDataException("Missing router policy");
        policy.Validate(); return policy;
    }
    public void Validate()
    {
        if (BotUsername != "TheKhadangBot" || BotId <= 0 || OwnerId <= 0 || !ChatId.ToString().StartsWith("-100") ||
            !OwnerSid.StartsWith("S-1-5-21-") || CodexSha256.Length != 64 || !CodexSha256.All(Uri.IsHexDigit) ||
            MaximumSessions is < 1 or > 3 || StartSpacingSeconds is < 1 or > 60)
            throw new InvalidDataException("Invalid PC-only owner policy");
        foreach (var path in new[] { CodexExecutable, CredentialFile, StateDirectory, WorkspaceRoot }) WindowsPath(path);
        if (LinuxWorkspaceRoot != null) LinuxPath(LinuxWorkspaceRoot);
        if (LinuxCodex != null)
        {
            LinuxCodex.Validate();
            if (LinuxWorkspaceRoot != LinuxCodexRuntime.WorkspaceRoot)
                throw new InvalidDataException("Linux Codex requires the preserved ordinary-owner workspace root");
        }
        if (LinuxClaude != null)
        {
            LinuxClaude.Validate();
            if (LinuxWorkspaceRoot != LinuxCodexRuntime.WorkspaceRoot)
                throw new InvalidDataException("Linux Claude requires the preserved ordinary-owner workspace root");
        }
        var seen = new HashSet<long> { ChatId };
        if (AdditionalChats is { Length: > 32 }) throw new InvalidDataException("Too many migration chats");
        foreach (var route in AdditionalChats ?? [])
        {
            if (route == null || route.Chat >= 0 || route.Chat < -4_503_599_627_370_495L ||
                route.IsForum && !route.Chat.ToString().StartsWith("-100") || !seen.Add(route.Chat))
                throw new InvalidDataException("Invalid or duplicate migration chat");
            ValidateParticipants(route.ParticipantIds);
        }
        ValidateParticipants(ParticipantIds);
    }
    private void ValidateParticipants(long[]? participants)
    {
        if (participants is { Length: > 64 } || (participants ?? []).Any(id => id <= 0 || id > 4_503_599_627_370_495L || id == OwnerId) ||
            (participants ?? []).Distinct().Count() != (participants?.Length ?? 0))
            throw new InvalidDataException("Exact unique non-owner Telegram participant IDs required");
    }
    public static string WindowsPath(string path)
    {
        if (path.Length < 4 || !char.IsAsciiLetter(path[0]) || path[1] != ':' || path[2] != '\\' ||
            path.Contains('/') || path.Split('\\').Any(part => part is "." or "..") || path.Any(char.IsControl) ||
            path.AsSpan(2).Contains(':') || path.StartsWith("\\"))
            throw new InvalidDataException("Only explicit local Windows paths are permitted");
        return path.TrimEnd('\\');
    }
    public void Workspace(string path, bool verifyFilesystem = true)
    {
        path = WindowsPath(path);
        if (!path.StartsWith(WindowsPath(WorkspaceRoot) + "\\", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Workspace is outside the protected PC root");
        if (OperatingSystem.IsWindows() && verifyFilesystem)
        {
            var current = new DirectoryInfo(path);
            while (current != null)
            {
                if ((current.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Workspace reparse points are not permitted");
                current = current.Parent;
            }
        }
    }
    public static string LinuxPath(string path)
    {
        if (!path.StartsWith("/Users/pouya/", StringComparison.Ordinal) || path.Contains('\\') || path.Contains("//") ||
            path.Any(char.IsControl) || path.Split('/').Any(part => part is "." or ".."))
            throw new InvalidDataException("Explicit ordinary-owner Linux path required");
        return path.TrimEnd('/');
    }
    public void Workspace(Binding binding, bool verifyFilesystem = true)
    {
        if (binding.Runtime == "windows") { Workspace(binding.Workspace, verifyFilesystem); return; }
        // Logical registry validation only. The attested Linux launcher must
        // independently verify actual paths/owner/OS credential denial.
        if (binding.Runtime != "linux" || LinuxWorkspaceRoot == null ||
            !(LinuxPath(binding.Workspace).StartsWith(LinuxPath(LinuxWorkspaceRoot) + "/", StringComparison.Ordinal) ||
              binding.Backend == "codex" && LinuxCodex != null && binding.Workspace == LinuxCodexRuntime.AndroidWorkspace))
            throw new InvalidDataException("Linux workspace is outside the explicitly admitted PC root");
    }
    private bool HumanMessage(JsonElement message, out long user, bool allowForwardedContent = false)
    {
        user = 0;
        return message.ValueKind == JsonValueKind.Object && message.TryGetProperty("from", out var sender) && sender.ValueKind == JsonValueKind.Object &&
            sender.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.Number && id.TryGetInt64(out user) && user > 0 &&
            sender.TryGetProperty("is_bot", out var bot) && bot.ValueKind == JsonValueKind.False &&
            TryAddress(message, out _) &&
            !new[] { "sender_chat", "via_bot" }.Any(key => message.TryGetProperty(key, out _)) &&
            (allowForwardedContent || !IsForwarded(message));
    }
    private static bool IsForwarded(JsonElement message) =>
        message.TryGetProperty("forward_origin", out _) || message.TryGetProperty("forward_date", out _);
    public bool OwnerMessage(JsonElement message) => HumanMessage(message, out var user) && user == OwnerId;

    // Normal conversation access across admitted chats/topics, never owner
    // authority. Slash controls and the legacy model-switch alias fail closed
    // before either native backend or attachment download can be invoked.
    public bool ConversationMessage(JsonElement message)
    {
        // Telegram's `from` is the human who sent this update. Forward origin
        // is untrusted content provenance, not a replacement sender identity.
        // Permit approved humans to forward files/text, never relay controls.
        if (!HumanMessage(message, out var user, allowForwardedContent: true)) return false;
        if (!TryAddress(message, out var address)) return false;
        var chatParticipants = (AdditionalChats ?? []).FirstOrDefault(route => route.Chat == address.Chat)?.ParticipantIds ?? [];
        if (user != OwnerId && !(ParticipantIds ?? []).Contains(user) && !chatParticipants.Contains(user)) return false;
        if (user == OwnerId && !IsForwarded(message)) return true;
        if (message.TryGetProperty("text", out var text) && text.ValueKind == JsonValueKind.String &&
            (text.GetString()!.TrimStart().StartsWith('/') || ModelCommand.TryParse(text.GetString()!, BotUsername, out _))) return false;
        return true;
    }

    public bool TryChat(long chat, out bool isForum)
    {
        if (chat == ChatId) { isForum = true; return true; }
        var route = (AdditionalChats ?? []).FirstOrDefault(r => r.Chat == chat);
        isForum = route?.IsForum ?? false;
        return route != null;
    }

    // Topic 0 is ONLY the explicitly admitted whole-group route. Missing topic
    // in a forum is Telegram's General topic (1), never a whole-group alias.
    public bool TryAddress(JsonElement message, out TopicAddress address)
    {
        address = default;
        if (message.ValueKind != JsonValueKind.Object || !message.TryGetProperty("chat", out var chat) ||
            chat.ValueKind != JsonValueKind.Object || !chat.TryGetProperty("id", out var id) ||
            id.ValueKind != JsonValueKind.Number || !id.TryGetInt64(out var number) || !TryChat(number, out var isForum)) return false;
        var hasForum = chat.TryGetProperty("is_forum", out var forum);
        if (isForum ? !hasForum || forum.ValueKind != JsonValueKind.True : hasForum && forum.ValueKind != JsonValueKind.False) return false;
        var hasTopic = message.TryGetProperty("message_thread_id", out var topic);
        if (!isForum)
        {
            if (hasTopic) return false;
            address = new(number, 0); return true;
        }
        int value = 1;
        if (hasTopic && (topic.ValueKind != JsonValueKind.Number || !topic.TryGetInt32(out value) || value <= 0)) return false;
        address = new(number, value); return true;
    }

    public void ValidateBindings(IReadOnlyList<Binding> bindings)
    {
        var addresses = new HashSet<TopicAddress>();
        var threads = new HashSet<string>(StringComparer.Ordinal);
        foreach (var binding in bindings)
        {
            if (!TryChat(binding.Chat, out var isForum) || (isForum ? binding.Topic <= 0 : binding.Topic != 0) ||
                string.IsNullOrWhiteSpace(binding.ThreadId) || !addresses.Add(binding.Address) || !threads.Add(binding.ThreadId))
                throw new InvalidDataException("Foreign, duplicate or ambiguous native binding in PC registry");
            if (binding.Backend is not ("codex" or "claude") || binding.Runtime is not ("windows" or "linux") ||
                binding.Backend == "claude" && !Guid.TryParseExact(binding.ThreadId, "D", out _))
                throw new InvalidDataException("Exact selected native backend/runtime/session required");
            Workspace(binding);
        }
    }
}

public sealed record ChatRoute(long Chat, bool IsForum = true, long[]? ParticipantIds = null);
public readonly record struct TopicAddress(long Chat, int Topic);
public sealed record Binding(long Chat, int Topic, string Name, string Workspace, string ThreadId,
    string Backend = "codex", string Runtime = "windows")
{
    [JsonIgnore] public TopicAddress Address => new(Chat, Topic);
}

public sealed class RollingBubble
{
    private readonly object gate = new();
    private sealed record Entry(string? Id, string Text, bool Important = false);
    private readonly List<Entry> entries = [];
    public string Tail { get { lock (gate) return Display(entries); } }
    private string Body() => string.Join("\n\n", entries.Select(e => e.Text));
    private static bool IsTool(Entry row) => row.Id is { } id &&
        (id.StartsWith("ctool:", StringComparison.Ordinal) || id.StartsWith("tool:", StringComparison.Ordinal));
    private static string Display(IEnumerable<Entry> values)
    {
        var rows = values.ToArray(); var output = new List<string>();
        for (var index = 0; index < rows.Length; index++)
        {
            var row = rows[index];
            if (IsTool(row))
            {
                var tools = new List<Entry> { row };
                while (index + 1 < rows.Length && IsTool(rows[index + 1])) tools.Add(rows[++index]);
                var shown = tools.Where((entry, position) => entry.Important || position >= tools.Count - 3).ToArray();
                if (tools.Count > shown.Length) output.Add("⏺ … " + (tools.Count - shown.Length) + " earlier tool calls");
                output.AddRange(shown.Select(entry => entry.Text));
            }
            else output.Add((row.Id?.StartsWith("cagent:", StringComparison.Ordinal) ?? false) ? "⏺ " + row.Text.TrimStart() : row.Text);
        }
        return string.Join("\n\n", output);
    }
    public void Append(string text)
    {
        lock (gate)
        {
            if (string.IsNullOrEmpty(text)) return;
            entries.Add(new(null, NativeGoal.Redact(text))); Trim();
        }
    }
    public void Upsert(string id, string text, bool delta = false, bool important = false)
    {
        lock (gate)
        {
            var index = entries.FindIndex(e => e.Id == id);
            var value = NativeGoal.Redact(delta && index >= 0 ? entries[index].Text + text : text);
            if (index < 0) entries.Add(new(id, value, important)); else entries[index] = new(id, value, important || entries[index].Important);
            Trim();
        }
    }
    public void Remove(string prefix)
    {
        lock (gate) entries.RemoveAll(e => e.Id?.StartsWith(prefix, StringComparison.Ordinal) ?? false);
    }
    private void Trim()
    {
        // Bound retained raw tool history independently of the compact view.
        // Tool spam must not evict recent assistant text before it is rendered.
        while (Body().Length > 30000)
        {
            var tool = entries.FindIndex(e => IsTool(e) && !e.Important);
            if (tool < 0) break;
            entries.RemoveAt(tool);
        }
        while (entries.Count > 1 && Display(entries).Length > 7000)
        {
            var index = entries.FindIndex(e => !(e.Id?.StartsWith("question:", StringComparison.Ordinal) ?? false));
            if (index < 0) index = 0;
            var excess = Display(entries).Length - 7000;
            if (entries[index].Text.Length > excess + 80)
            {
                entries[index] = entries[index] with { Text = LineTail(entries[index].Text, entries[index].Text.Length - excess - 4) };
                continue;
            }
            entries.RemoveAt(index);
        }
        if (entries.Count == 1 && entries[0].Text.Length > 7000)
            entries[0] = entries[0] with { Text = LineTail(entries[0].Text, 7000) };
    }
    public string Render(TimeSpan elapsed, string? goal = null, string state = "Working")
    {
        lock (gate)
        {
            var duration = elapsed.TotalHours >= 1 ? (int)elapsed.TotalHours + "h " + elapsed.Minutes + "m " + elapsed.Seconds + "s" :
                elapsed.TotalMinutes >= 1 ? elapsed.Minutes + "m " + elapsed.Seconds + "s" : elapsed.Seconds + "s";
            var footer = "\n\n" + state + " (" + duration + ")";
            if (!string.IsNullOrWhiteSpace(goal)) footer += "\nGoal: " + SafeTail(goal, 160);
            var available = 3900 - footer.Length;
            var body = NativeEventView.CompactLegacyBubble(Display(entries).Trim());
            var pending = string.Join("\n\n", entries.Where(e => e.Id?.StartsWith("question:", StringComparison.Ordinal) ?? false).Select(e => e.Text));
            if (pending.Length > 0)
            {
                var activity = Display(entries.Where(e => !(e.Id?.StartsWith("question:", StringComparison.Ordinal) ?? false))).Trim();
                // Pending owner action remains visible even as later tools roll.
                var question = LineTail(pending, Math.Min(1800, available));
                body = LineTail(activity, Math.Max(0, available - question.Length - 2)) + "\n\n" + question;
            }
            return LineTail(body.Length == 0 ? "Connected to the PC session." : body, available) + footer;
        }
    }
    public static string LineTail(string text, int length)
    {
        if (length <= 0) return "";
        if (text.Length <= length) return text;
        if (length < 3) return SafeTail(text, length);
        var tail = SafeTail(text, length - 2);
        var newline = tail.IndexOf('\n');
        if (newline >= 0 && newline < tail.Length / 2) tail = tail[(newline + 1)..];
        return "…\n" + tail;
    }
    public static string SafeTail(string text, int length)
    {
        var start = Math.Max(0, text.Length - length);
        if (start > 0 && char.IsLowSurrogate(text[start])) start++;
        return text[start..];
    }
}
