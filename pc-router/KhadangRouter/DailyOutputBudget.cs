using System.Globalization;
using System.Text.Json;

namespace KhadangRouter;

internal sealed class DailyOutputLimit : Exception { }

// New automatic Telegram messages, not edits/typing/owner controls. Reserve
// BEFORE HTTP; ambiguous attempts retain their slot across service restarts.
internal sealed class DailyOutputBudget(Ledger ledger, TimeProvider? clock = null)
{
    internal const int Limit = 100;
    private static readonly TimeZoneInfo Zone = Pacific();
    private readonly TimeProvider time = clock ?? TimeProvider.System;
    internal sealed record State(int Seeded, string[] Reserved);
    internal sealed record Reservation(string Key, string Token);
    private static TimeZoneInfo Pacific()
    {
        try { return TimeZoneInfo.FindSystemTimeZoneById("America/Los_Angeles"); }
        catch (TimeZoneNotFoundException) { return TimeZoneInfo.FindSystemTimeZoneById("Pacific Standard Time"); }
    }
    private (string Key, DateTimeOffset Start, DateTimeOffset End) Day(long chat, int topic)
    {
        var local = TimeZoneInfo.ConvertTime(time.GetUtcNow(), Zone).Date;
        var start = new DateTimeOffset(TimeZoneInfo.ConvertTimeToUtc(local, Zone), TimeSpan.Zero);
        var end = new DateTimeOffset(TimeZoneInfo.ConvertTimeToUtc(local.AddDays(1), Zone), TimeSpan.Zero);
        return ($"telegram/daily-output/{chat}/{topic}/{local.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)}", start, end);
    }
    internal Reservation Reserve(long chat, int topic)
    {
        Reservation result = null!;
        bool limited = false;
        ledger.Transaction(() => {
            var day = Day(chat, topic);
            var state = ledger.Get(day.Key)?.Deserialize<State>();
            if (state == null)
            {
                // Include today's pre-upgrade automatic deliveries. Classic
                // answers have entities, unlike plain owner-control replies.
                var seed = int.Parse(ledger.Query("SELECT COUNT(*) FROM operations WHERE status='confirmed' AND " +
                    "kind IN ('telegram/sendMessage','telegram/sendRichMessage','telegram/sendPhoto','telegram/sendDocument') " +
                    "AND json_extract(payload,'$.chat_id')=? AND COALESCE(json_extract(payload,'$.message_thread_id'),0)=? " +
                    "AND json_extract(result,'$.date')>=? AND json_extract(result,'$.date')<? " +
                    "AND (kind<>'telegram/sendMessage' OR json_type(payload,'$.entities') IS NOT NULL)",
                    chat, topic, day.Start.ToUnixTimeSeconds(), day.End.ToUnixTimeSeconds())[0][0]!);
                state = new(Math.Min(seed, Limit), []);
                ledger.Put(day.Key, state);
            }
            if (state.Seeded is < 0 or > Limit || state.Reserved.Length > Limit ||
                state.Reserved.Distinct(StringComparer.Ordinal).Count() != state.Reserved.Length ||
                state.Reserved.Any(token => !Guid.TryParseExact(token, "N", out _)))
                throw new InvalidDataException("Invalid durable daily output budget");
            if (state.Seeded + state.Reserved.Length >= Limit) { limited = true; return; }
            var token = Guid.NewGuid().ToString("N");
            ledger.Put(day.Key, state with { Reserved = [.. state.Reserved, token] });
            result = new(day.Key, token);
        });
        if (limited) throw new DailyOutputLimit();
        return result;
    }
    internal void Release(Reservation reservation)
    {
        ledger.Transaction(() => {
            var state = ledger.Get(reservation.Key)?.Deserialize<State>() ?? throw new InvalidDataException("Missing output reservation");
            if (state.Reserved.Contains(reservation.Token, StringComparer.Ordinal))
                ledger.Put(reservation.Key, state with { Reserved = state.Reserved.Where(token => token != reservation.Token).ToArray() });
        });
    }
}

internal sealed class DailyLimitedBot(IBot inner, DailyOutputBudget budget) : IBot
{
    private async Task<JsonElement> Send(long chat, int topic, Func<Task<JsonElement>> action)
    {
        var reservation = budget.Reserve(chat, topic);
        try { return await action(); }
        catch (TelegramFailure rejected) when (rejected.Code is 400 or 403 or 413 or 429)
        { budget.Release(reservation); throw; } // Explicit rejection only, never timeout/cancellation.
    }
    public Task<JsonElement> SendBubble(long chat, int topic, string text, CancellationToken stop) =>
        Send(chat, topic, () => inner.SendBubble(chat, topic, text, stop));
    public Task<JsonElement> SendAnswer(long chat, int topic, AnswerPart part, CancellationToken stop) =>
        Send(chat, topic, () => inner.SendAnswer(chat, topic, part, stop));
    public Task<JsonElement> Upload(long chat, int topic, string name, byte[] bytes, bool photo, CancellationToken stop) =>
        Send(chat, topic, () => inner.Upload(chat, topic, name, bytes, photo, stop));
    public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => inner.Call(method, parameters, stop, effect);
    public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => inner.Send(chat, topic, text, stop);
    public Task Edit(long chat, int message, string text, CancellationToken stop) => inner.Edit(chat, message, text, stop);
    public Task EditBubble(long chat, int message, string text, CancellationToken stop) => inner.EditBubble(chat, message, text, stop);
    public Task<bool> Typing(long chat, int topic, CancellationToken stop) => inner.Typing(chat, topic, stop);
}
