using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace KhadangRouter;

public sealed class TelegramFailure(int code, int retryAfter = 0, bool notModified = false) : Exception("Telegram request failed; code=" + code)
{
    public int Code { get; } = code;
    public int RetryAfter { get; } = retryAfter;
    public bool NotModified { get; } = notModified;
}

public sealed class Telegram : IBot, IDisposable
{
    private readonly HttpClient http = new(new HttpClientHandler { AllowAutoRedirect = false });
    private readonly string endpoint;
    private readonly string filesEndpoint;
    private readonly Ledger ledger;
    private readonly SemaphoreSlim outbound = new(1, 1);
    public Telegram(string token, Ledger ledger)
    {
        if (string.IsNullOrWhiteSpace(token) || token.Any(char.IsWhiteSpace)) throw new InvalidDataException("Bot credential missing");
        endpoint = "https://api.telegram.org/bot" + token + "/"; this.ledger = ledger;
        filesEndpoint = "https://api.telegram.org/file/bot" + token + "/";
        http.Timeout = TimeSpan.FromSeconds(45);
    }
    public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
    {
        if (!new[] { "getMe", "getWebhookInfo", "getChat", "getChatMember", "getUpdates", "getFile", "sendMessage", "sendRichMessage", "editMessageText", "createForumTopic", "setMyCommands", "getMyCommands", "answerCallbackQuery", "sendChatAction" }.Contains(method))
            throw new InvalidOperationException("Unknown Telegram method");
        if (method == "sendChatAction" && effect)
            throw new InvalidOperationException("Ephemeral typing must not create a durable action or replay hold");
        string? attempt = effect ? ledger.Attempt("telegram/" + method, parameters) : null;
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, endpoint + method) { Content = JsonContent.Create(parameters) };
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, stop);
            // Buffer is bounded: do not let untrusted provider data exhaust the service.
            if (response.Content.Headers.ContentLength > 2_097_152) throw new InvalidDataException("Bot response too large");
            await using var source = await response.Content.ReadAsStreamAsync(stop);
            using var buffer = new MemoryStream(); var chunk = new byte[8192]; int length;
            while ((length = await source.ReadAsync(chunk, stop)) != 0)
            {
                if (buffer.Length + length > 2_097_152) throw new InvalidDataException("Bot response too large");
                buffer.Write(chunk, 0, length);
            }
            var raw = buffer.ToArray();
            using var document = JsonDocument.Parse(raw);
            var root = document.RootElement;
            if (!root.GetProperty("ok").GetBoolean())
            {
                var code = root.TryGetProperty("error_code", out var c) ? c.GetInt32() : (int)response.StatusCode;
                var retry = root.TryGetProperty("parameters", out var p) && p.TryGetProperty("retry_after", out var r) ? r.GetInt32() : 0;
                if (attempt != null) ledger.Outcome(attempt, "rejected");
                var notModified = method == "editMessageText" && code == 400 && root.TryGetProperty("description", out var d) &&
                    (d.GetString()?.Contains("message is not modified", StringComparison.OrdinalIgnoreCase) ?? false);
                throw new TelegramFailure(code, retry, notModified);
            }
            if (!response.IsSuccessStatusCode) throw new TelegramFailure((int)response.StatusCode);
            var result = root.GetProperty("result").Clone();
            if (attempt != null) ledger.Confirm(attempt, result);
            return result;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
        {
            if (attempt != null) ledger.Outcome(attempt, "unknown");
            // Never print HttpClient's URL-bearing exception or replay an effect.
            throw new TelegramFailure(0);
        }
        catch
        {
            if (attempt != null) ledger.Outcome(attempt, "unknown");
            throw;
        }
    }
    internal static Dictionary<string, object> TypingParameters(long chat, int topic)
    {
        if (topic < 0) throw new InvalidDataException("Invalid Telegram topic");
        var parameters = new Dictionary<string, object> { ["chat_id"] = chat, ["action"] = "typing" };
        if (topic > 0) parameters["message_thread_id"] = topic;
        return parameters;
    }
    public async Task<bool> Typing(long chat, int topic, CancellationToken stop)
    {
        // A receipt pulse bypasses the message/edit queue. Failure is cosmetic;
        // never turn it into an unknown native input or durable send operation.
        var result = await Call("sendChatAction", TypingParameters(chat, topic), stop);
        return result.ValueKind == JsonValueKind.True;
    }
    public async Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
    {
        await outbound.WaitAsync(stop);
        try
        {
            return await Call("sendMessage", SendParameters(chat, topic, text), stop, effect: true);
        }
        finally { outbound.Release(); }
    }
    internal static Dictionary<string, object> SendParameters(long chat, int topic, string text)
    {
        if (topic < 0) throw new InvalidDataException("Invalid Telegram topic");
        var parameters = new Dictionary<string, object> { ["chat_id"] = chat, ["text"] = text,
            ["disable_notification"] = true, ["link_preview_options"] = new { is_disabled = true } };
        if (topic > 0) parameters["message_thread_id"] = topic;
        return parameters;
    }
    public async Task Edit(long chat, int message, string text, CancellationToken stop)
    {
        await outbound.WaitAsync(stop);
        try { await Call("editMessageText", new { chat_id = chat, message_id = message, text,
            link_preview_options = new { is_disabled = true } }, stop, effect: true); }
        finally { outbound.Release(); }
    }
    // Format only the rolling native bubble. Controls and questions stay plain.
    // Explicit entities keep literal backticks/HTML safe and consume no text budget.
    internal static Dictionary<string, object> BubbleSendParameters(long chat, int topic, string text)
    {
        var parameters = SendParameters(chat, topic, text);
        parameters["entities"] = BubbleEntities(text);
        return parameters;
    }
    internal static Dictionary<string, object> BubbleEditParameters(long chat, int message, string text) => new() {
        ["chat_id"] = chat, ["message_id"] = message, ["text"] = text,
        ["entities"] = BubbleEntities(text), ["link_preview_options"] = new { is_disabled = true }
    };
    internal sealed record BubbleEntity(string type, int offset, int length);
    internal static BubbleEntity[] BubbleEntities(string text)
    {
        var entities = new List<BubbleEntity>();
        int block = 0, line = 0;
        while (line < text.Length)
        {
            var end = text.IndexOf('\n', line);
            if (end < 0) end = text.Length;
            // Remote Control links must remain outside a pre entity to be tappable.
            if (text.AsSpan(line, end - line).StartsWith("Claude app: https://claude.ai/code/", StringComparison.Ordinal))
            {
                if (line > block) entities.Add(new("pre", block, line - block));
                var url = line + "Claude app: ".Length;
                entities.Add(new("url", url, end - url));
                block = Math.Min(end + 1, text.Length);
            }
            line = end < text.Length ? end + 1 : text.Length;
        }
        if (block < text.Length) entities.Add(new("pre", block, text.Length - block));
        return entities.ToArray(); // .NET indices and Telegram offsets are both UTF-16.
    }
    public async Task<JsonElement> SendBubble(long chat, int topic, string text, CancellationToken stop)
    {
        await outbound.WaitAsync(stop);
        try { return await Call("sendMessage", BubbleSendParameters(chat, topic, text), stop, effect: true); }
        finally { outbound.Release(); }
    }
    public async Task EditBubble(long chat, int message, string text, CancellationToken stop)
    {
        await outbound.WaitAsync(stop);
        try { await Call("editMessageText", BubbleEditParameters(chat, message, text), stop, effect: true); }
        finally { outbound.Release(); }
    }
    internal static Dictionary<string, object> AnswerParameters(long chat, int topic, AnswerPart part)
    {
        if (part.RichHtml != null)
        {
            if (topic < 0 || part.Entities.Length != 0 || !RichTables.TryRender(part.Text, out var html) || html != part.RichHtml)
                throw new InvalidDataException("Invalid native table answer");
            var rich = new Dictionary<string, object> { ["chat_id"] = chat, ["rich_message"] = new { html } };
            if (topic > 0) rich["message_thread_id"] = topic;
            return rich; // Clean final: notifying, not a live bubble or code block.
        }
        var parameters = SendParameters(chat, topic, part.Text);
        parameters.Remove("disable_notification"); // Final answer, not silent progress.
        parameters["entities"] = part.Entities;
        return parameters;
    }
    internal static string AnswerMethod(AnswerPart part) => part.RichHtml == null ? "sendMessage" : "sendRichMessage";
    public async Task<JsonElement> SendAnswer(long chat, int topic, AnswerPart part, CancellationToken stop)
    {
        await outbound.WaitAsync(stop);
        try { return await Call(AnswerMethod(part), AnswerParameters(chat, topic, part), stop, effect: true); }
        finally { outbound.Release(); }
    }
    public async Task<JsonElement> Upload(long chat, int topic, string filename, byte[] bytes, bool photo, CancellationToken stop)
    {
        if (topic < 0 || filename.Length is < 1 or > 255 || filename.Any(char.IsControl) || filename.IndexOfAny(['/', '\\', '"']) >= 0 ||
            bytes.Length is <= 0 or > OutboundFiles.MaximumBytes || photo && !OutboundFiles.Photo(bytes))
            throw new InvalidDataException("Invalid bounded attachment upload");
        await outbound.WaitAsync(stop);
        string? attempt = null;
        try
        {
            var method = photo ? "sendPhoto" : "sendDocument";
            using var content = new MultipartFormDataContent();
            content.Add(new StringContent(chat.ToString(System.Globalization.CultureInfo.InvariantCulture)), "chat_id");
            if (topic > 0) content.Add(new StringContent(topic.ToString(System.Globalization.CultureInfo.InvariantCulture)), "message_thread_id");
            content.Add(new StringContent(filename), "caption");
            var media = new ByteArrayContent(bytes);
            media.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(photo ?
                bytes[0] == 137 ? "image/png" : "image/jpeg" : "application/octet-stream");
            content.Add(media, photo ? "photo" : "document", filename);
            attempt = ledger.Attempt("telegram/" + method, new { chat_id = chat, message_thread_id = topic, filename,
                size = bytes.Length, sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant() });
            using var request = new HttpRequestMessage(HttpMethod.Post, endpoint + method) { Content = content };
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, stop);
            if (response.Content.Headers.ContentLength > 2_097_152) throw new InvalidDataException("Bot response too large");
            await using var stream = await response.Content.ReadAsStreamAsync(stop);
            using var buffer = new MemoryStream(); var chunk = new byte[8192]; int count;
            while ((count = await stream.ReadAsync(chunk, stop)) != 0)
            {
                if (buffer.Length + count > 2_097_152) throw new InvalidDataException("Bot response too large");
                buffer.Write(chunk, 0, count);
            }
            using var doc = JsonDocument.Parse(buffer.ToArray()); var root = doc.RootElement;
            if (!root.GetProperty("ok").GetBoolean())
            {
                var code = root.TryGetProperty("error_code", out var c) ? c.GetInt32() : (int)response.StatusCode;
                var retry = root.TryGetProperty("parameters", out var p) && p.TryGetProperty("retry_after", out var r) ? r.GetInt32() : 0;
                ledger.Outcome(attempt, "rejected"); throw new TelegramFailure(code, retry);
            }
            if (!response.IsSuccessStatusCode) throw new TelegramFailure(0);
            var result = root.GetProperty("result").Clone();
            if (result.GetProperty("message_id").GetInt32() <= 0 || result.GetProperty("chat").GetProperty("id").GetInt64() != chat ||
                topic > 0 && (!result.TryGetProperty("message_thread_id", out var thread) || thread.GetInt32() != topic) ||
                !result.TryGetProperty(photo ? "photo" : "document", out _))
                throw new InvalidDataException("Upload receipt target or media mismatch");
            ledger.Confirm(attempt, result); return result;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
        {
            if (attempt != null) ledger.Outcome(attempt, "unknown");
            throw new TelegramFailure(0); // Never expose token-bearing HTTP URL.
        }
        catch
        {
            if (attempt != null) ledger.Outcome(attempt, "unknown");
            throw;
        }
        finally { outbound.Release(); }
    }
    public static string DownloadPath(JsonElement result, AttachmentReference file)
    {
        if (result.ValueKind != JsonValueKind.Object) throw new AttachmentFailure("Malformed Telegram file metadata");
        if (file.UniqueId != null && (!result.TryGetProperty("file_unique_id", out var unique) || unique.GetString() != file.UniqueId))
            throw new AttachmentFailure("Telegram attachment identity changed");
        if (result.TryGetProperty("file_size", out var size))
        {
            if (!size.TryGetInt64(out var bytes) || bytes < 0 || bytes > Attachments.MaximumBytes || file.Size is { } expected && expected != bytes)
                throw new AttachmentFailure("Telegram attachment size changed or exceeds hosted download limit");
        }
        var path = result.GetProperty("file_path").GetString();
        if (path == null || path.Length > 512 || !System.Text.RegularExpressions.Regex.IsMatch(path, "\\A[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)+\\z") ||
            path.Split('/').Any(part => part is "." or "..")) throw new AttachmentFailure("Unsafe Telegram download path refused");
        return path;
    }
    public static async Task CopyAttachment(Stream source, Stream target, long? expected, CancellationToken stop)
    {
        long total = 0; var buffer = new byte[65536]; int count;
        while ((count = await source.ReadAsync(buffer, stop)) != 0)
        {
            total += count;
            if (total > Attachments.MaximumBytes || expected is { } length && total > length) throw new AttachmentFailure("Attachment stream exceeds its bounded length");
            await target.WriteAsync(buffer.AsMemory(0, count), stop);
        }
        if (expected is { } bytes && total != bytes) throw new AttachmentFailure("Attachment download was truncated");
    }
    public async Task Download(AttachmentReference file, Stream target, CancellationToken stop)
    {
        try
        {
            var result = await Call("getFile", new { file_id = file.FileId }, stop);
            var path = DownloadPath(result, file);
            var expectedBytes = file.Size ?? (result.TryGetProperty("file_size", out var returnedSize) ? returnedSize.GetInt64() : (long?)null);
            using var request = new HttpRequestMessage(HttpMethod.Get, filesEndpoint + path);
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, stop);
            if (!response.IsSuccessStatusCode) throw new TelegramFailure((int)response.StatusCode);
            if (response.Content.Headers.ContentLength is { } declared && (declared > Attachments.MaximumBytes || expectedBytes is { } expected && declared != expected))
                throw new AttachmentFailure("Attachment HTTP length exceeds or differs from reference");
            await using var source = await response.Content.ReadAsStreamAsync(stop);
            await CopyAttachment(source, target, expectedBytes, stop);
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
        {
            // Never propagate an exception containing the credential-bearing
            // download URL into a bubble, diagnostic or native model input.
            throw new TelegramFailure(0);
        }
    }
    public void Dispose() { http.Dispose(); outbound.Dispose(); }
}
