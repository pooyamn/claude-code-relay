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
    private readonly Ledger ledger;
    private readonly SemaphoreSlim outbound = new(1, 1);
    public Telegram(string token, Ledger ledger)
    {
        if (string.IsNullOrWhiteSpace(token) || token.Any(char.IsWhiteSpace)) throw new InvalidDataException("Bot credential missing");
        endpoint = "https://api.telegram.org/bot" + token + "/"; this.ledger = ledger;
        http.Timeout = TimeSpan.FromSeconds(45);
    }
    public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
    {
        if (!new[] { "getMe", "getWebhookInfo", "getChat", "getChatMember", "getUpdates", "sendMessage", "editMessageText", "createForumTopic", "setMyCommands", "getMyCommands", "answerCallbackQuery" }.Contains(method))
            throw new InvalidOperationException("Unknown Telegram method");
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
    public async Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
    {
        await outbound.WaitAsync(stop);
        try
        {
            return await Call("sendMessage", new { chat_id = chat, message_thread_id = topic, text,
                disable_notification = true, link_preview_options = new { is_disabled = true } }, stop, effect: true);
        }
        finally { outbound.Release(); }
    }
    public async Task Edit(long chat, int message, string text, CancellationToken stop)
    {
        await outbound.WaitAsync(stop);
        try { await Call("editMessageText", new { chat_id = chat, message_id = message, text,
            link_preview_options = new { is_disabled = true } }, stop, effect: true); }
        finally { outbound.Release(); }
    }
    public void Dispose() { http.Dispose(); outbound.Dispose(); }
}
