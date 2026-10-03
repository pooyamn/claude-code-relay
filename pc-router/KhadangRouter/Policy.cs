using System.Text.Json;
using System.Text.Json.Serialization;

namespace KhadangRouter;

public sealed record RouterPolicy(string BotUsername, long BotId, long OwnerId, long ChatId,
    string OwnerSid, string CodexExecutable, string CodexSha256, string CredentialFile,
    string StateDirectory, string WorkspaceRoot, int MaximumSessions = 3, int StartSpacingSeconds = 5,
    bool OwnerFullAccess = false, ChatRoute[]? AdditionalChats = null)
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
        var seen = new HashSet<long> { ChatId };
        if (AdditionalChats is { Length: > 32 }) throw new InvalidDataException("Too many migration chats");
        foreach (var route in AdditionalChats ?? [])
            if (route == null || route.Chat >= 0 || route.Chat < -4_503_599_627_370_495L ||
                route.IsForum && !route.Chat.ToString().StartsWith("-100") || !seen.Add(route.Chat))
                throw new InvalidDataException("Invalid or duplicate migration chat");
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
    public bool OwnerMessage(JsonElement message)
    {
        return message.ValueKind == JsonValueKind.Object && message.TryGetProperty("from", out var sender) && sender.ValueKind == JsonValueKind.Object &&
            sender.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.Number && id.TryGetInt64(out var user) && user == OwnerId &&
            sender.TryGetProperty("is_bot", out var bot) && bot.ValueKind == JsonValueKind.False &&
            TryAddress(message, out _) &&
            !new[] { "sender_chat", "forward_origin", "forward_date", "via_bot" }.Any(key => message.TryGetProperty(key, out _));
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
            Workspace(binding.Workspace);
        }
    }
}

public sealed record ChatRoute(long Chat, bool IsForum = true);
public readonly record struct TopicAddress(long Chat, int Topic);
public sealed record Binding(long Chat, int Topic, string Name, string Workspace, string ThreadId)
{
    [JsonIgnore] public TopicAddress Address => new(Chat, Topic);
}

public sealed class RollingBubble
{
    private readonly object gate = new();
    private string tail = "";
    public string Tail { get { lock (gate) return tail; } }
    public void Append(string text)
    {
        lock (gate)
        {
            tail += text;
            // Do not retain an unbounded duplicate of the native transcript.
            if (tail.Length > 7000) tail = SafeTail(tail, 7000);
        }
    }
    public string Render(TimeSpan elapsed, string? goal = null, string state = "Working")
    {
        lock (gate)
        {
            var footer = "\n\n" + state + " (" + (int)elapsed.TotalMinutes + "m " + elapsed.Seconds + "s)";
            if (!string.IsNullOrWhiteSpace(goal)) footer += "\nGoal: " + SafeTail(goal, 160);
            var available = 3900 - footer.Length;
            return SafeTail(tail.Length == 0 ? "Connected to the PC session." : tail.Trim(), available) + footer;
        }
    }
    public static string SafeTail(string text, int length)
    {
        var start = Math.Max(0, text.Length - length);
        if (start > 0 && char.IsLowSurrogate(text[start])) start++;
        return text[start..];
    }
}
