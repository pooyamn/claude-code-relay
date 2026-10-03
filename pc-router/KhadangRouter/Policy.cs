using System.Text.Json;
using System.Text.Json.Serialization;

namespace KhadangRouter;

public sealed record RouterPolicy(string BotUsername, long BotId, long OwnerId, long ChatId,
    string OwnerSid, string CodexExecutable, string CodexSha256, string CredentialFile,
    string StateDirectory, string WorkspaceRoot, int MaximumSessions = 3, int StartSpacingSeconds = 5,
    bool OwnerFullAccess = false)
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
            message.TryGetProperty("chat", out var chat) && chat.ValueKind == JsonValueKind.Object && chat.TryGetProperty("id", out var chatId) &&
            chatId.ValueKind == JsonValueKind.Number && chatId.TryGetInt64(out var number) && number == ChatId &&
            chat.TryGetProperty("is_forum", out var forum) && forum.ValueKind == JsonValueKind.True &&
            !new[] { "sender_chat", "forward_origin", "forward_date", "via_bot" }.Any(key => message.TryGetProperty(key, out _));
    }
}

public sealed record Binding(long Chat, int Topic, string Name, string Workspace, string ThreadId);

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
