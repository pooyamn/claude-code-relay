using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

internal sealed class FileDelivery
{
    public string Path { get; set; } = "";
    public string? Sha256 { get; set; }
    public long? Size { get; set; }
    public bool Document { get; set; }
    public int? Message { get; set; }
    public bool SendUnknown { get; set; }
    public string? Failure { get; set; }
}

public interface IOutboundFiles
{
    Task<byte[]> Read(Binding binding, string path, string? expectedSha256, CancellationToken stop);
}

public sealed class OutboundFiles(RouterPolicy policy, INative? linux) : IOutboundFiles
{
    public const int MaximumBytes = 20 * 1024 * 1024;
    internal static bool LiteralPath(string path) => path.Length is > 1 and <= 4096 && !path.Any(char.IsControl) &&
        Filename(path).Length is > 0 and <= 255 && !Filename(path).Contains('"') &&
        (path.StartsWith('/') && !path.Contains('\\') &&
            !path[1..].Split('/').Any(p => p is "" or "." or ".." or ".git" or ".codex" or ".claude" or ".ssh") ||
         path.Length > 3 && char.IsAsciiLetter(path[0]) && path[1..3] == ":\\" && !path.Contains('/') &&
            !path[3..].Split('\\').Any(p => p is "" or "." or ".." or ".git" or ".codex" or ".claude" or ".ssh" || p.Contains(':')));

    internal static (string Text, List<FileDelivery> Files) Extract(string text)
    {
        var result = new StringBuilder(); var files = new List<FileDelivery>(); var seen = new HashSet<string>(StringComparer.Ordinal);
        bool fenced = false;
        foreach (var line in text.Replace("\r\n", "\n").Split('\n'))
        {
            if (line.TrimStart().StartsWith("```", StringComparison.Ordinal)) fenced = !fenced;
            if (!fenced && line.StartsWith("📎 ", StringComparison.Ordinal))
            {
                var path = line[3..].Trim();
                if (seen.Add(path))
                {
                    if (files.Count >= 16) throw new InvalidDataException("Attachment count exceeds delivery bound");
                    files.Add(new() { Path = path, Failure = LiteralPath(path) ? null : "Invalid attachment path" });
                }
            }
            else result.AppendLine(line);
        }
        return (result.ToString().TrimEnd('\r', '\n'), files);
    }

    public async Task<byte[]> Read(Binding binding, string path, string? expectedSha256, CancellationToken stop)
    {
        if (!LiteralPath(path)) throw new InvalidDataException("Invalid attachment path");
        if (binding.Runtime == "windows")
            return WindowsOwnerProcess.ReadArtifact(policy, binding.Workspace, path, expectedSha256);
        if (linux == null || !path.StartsWith(binding.Workspace + "/", StringComparison.Ordinal))
            throw new InvalidDataException("Attachment is outside the topic project");
        using var result = new MemoryStream(); string? sha = expectedSha256; long size = -1;
        while (size < 0 || result.Length < size)
        {
            // Private connector method, handled by UID 1000 BEFORE forwarding
            // provider RPC. No command, daemon launch or model inference.
            var value = await linux.Call("ccrelay/artifact/read", new { workspace = binding.Workspace, path,
                offset = result.Length, sha256 = sha }, stop, effect: false);
            var length = value.GetProperty("size").GetInt64(); var digest = value.GetProperty("sha256").GetString()!;
            if (length is <= 0 or > MaximumBytes || size >= 0 && size != length ||
                value.GetProperty("offset").GetInt64() != result.Length || digest.Length != 64 || !digest.All(Uri.IsHexDigit) ||
                sha != null && sha != digest) throw new InvalidDataException("Attachment snapshot changed");
            size = length; sha = digest;
            var chunk = Convert.FromBase64String(value.GetProperty("data").GetString()!);
            if (chunk.Length is <= 0 or > 524288 || result.Length + chunk.Length > size)
                throw new InvalidDataException("Invalid bounded attachment chunk");
            result.Write(chunk);
        }
        var bytes = result.ToArray();
        if (Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() != sha)
            throw new InvalidDataException("Attachment snapshot digest mismatch");
        return bytes;
    }

    internal static string Filename(string path) => path.Replace('\\', '/').Split('/')[^1];
    internal static bool Photo(byte[] bytes) => bytes.Length <= 10 * 1024 * 1024 &&
        (bytes.AsSpan().StartsWith(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }) ||
         bytes.Length > 3 && bytes[0] == 255 && bytes[1] == 216 && bytes[2] == 255);
}
